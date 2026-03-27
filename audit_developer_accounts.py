from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from urllib.parse import quote_plus

import requests

from developer_watchlist import (
    APP_STORE_COUNTRY,
    APP_STORE_SEARCH_LIMIT,
    APP_STORE_SEARCH_URL_TEMPLATE,
    GOOGLE_PLAY_COUNTRY,
    GOOGLE_PLAY_LANG,
    GOOGLE_PLAY_SEARCH_LIMIT,
    is_app_store_game_candidate,
    is_google_play_game_candidate,
    load_core_developers,
    match_developer_id,
    match_developer_name,
    parse_app_store_release_date,
    parse_google_play_release_date,
)

try:
    from google_play_scraper import app as gp_app
    from google_play_scraper import search as gp_search
except Exception:
    gp_app = None
    gp_search = None


REQUEST_TIMEOUT = 30
STALE_ACCOUNT_DAYS = 365
CORE_DEVELOPERS_PATH = Path("core_developers.json")
TRIMMED_CORE_DEVELOPERS_PATH = Path("core_developers_trimmed.json")
AUDIT_REPORT_PATH = Path("developer_account_audit_report.json")


def normalize_text(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def is_app_store_game(item: dict[str, Any]) -> bool:
    primary_genre_name = item.get("primaryGenreName")
    genres = item.get("genres") or []
    genre_ids = {str(genre_id) for genre_id in (item.get("genreIds") or []) if genre_id is not None}
    return primary_genre_name == "Games" or "Games" in genres or "6014" in genre_ids


def is_google_play_game(details: dict[str, Any]) -> bool:
    genre_id = details.get("genreId")
    if isinstance(genre_id, str) and genre_id.startswith("GAME_"):
        return True
    for category in details.get("categories") or []:
        if isinstance(category, dict) and str(category.get("id") or "").startswith("GAME_"):
            return True
    return False


def parse_google_play_last_activity(details: dict[str, Any]) -> datetime | None:
    updated = details.get("updated")
    if isinstance(updated, str) and updated:
        for fmt in ("%b %d, %Y", "%B %d, %Y"):
            try:
                return datetime.strptime(updated, fmt).replace(tzinfo=timezone.utc)
            except ValueError:
                continue
    return parse_google_play_release_date(details)


def parse_app_store_last_activity(item: dict[str, Any]) -> datetime | None:
    for key in ("currentVersionReleaseDate", "releaseDate"):
        value = item.get(key)
        if isinstance(value, str) and value:
            try:
                return datetime.fromisoformat(value.replace("Z", "+00:00"))
            except ValueError:
                continue
    return parse_app_store_release_date(item)


def is_stale(last_activity_at: datetime | None, stale_days: int = STALE_ACCOUNT_DAYS, now: datetime | None = None) -> bool:
    if last_activity_at is None:
        return True
    current_time = now or datetime.now(timezone.utc)
    return last_activity_at < current_time - timedelta(days=stale_days)


def build_identifier_candidates(target: dict[str, Any]) -> list[str]:
    identifiers = [normalize_text(value) for value in target.get("developer_ids", []) if normalize_text(value)]
    if not identifiers:
        identifiers = [normalize_text(value) for value in target.get("developer_names", []) if normalize_text(value)]
    return identifiers


def fetch_app_store_apps_for_identifier(target: dict[str, Any], identifier: str) -> list[dict[str, Any]]:
    term = quote_plus(target["query"])
    url = APP_STORE_SEARCH_URL_TEMPLATE.format(
        term=term,
        country=APP_STORE_COUNTRY,
        limit=APP_STORE_SEARCH_LIMIT,
    )
    response = requests.get(url, timeout=REQUEST_TIMEOUT)
    response.raise_for_status()
    payload = response.json()
    results = payload.get("results", [])

    matched: list[dict[str, Any]] = []
    for item in results:
        if not is_app_store_game_candidate(item):
            continue
        if match_developer_id(item.get("artistId"), [identifier]) or match_developer_name(item.get("artistName"), [identifier]):
            matched.append(item)
    return matched


def fetch_google_play_apps_for_identifier(target: dict[str, Any], identifier: str) -> list[dict[str, Any]]:
    if gp_search is None or gp_app is None:
        raise RuntimeError("google-play-scraper is not installed.")

    queries = [identifier]
    target_query = normalize_text(target.get("query"))
    if target_query and target_query not in {normalize_text(identifier)}:
        queries.append(target["query"])

    matched_app_ids: list[str] = []
    for query in queries:
        results = gp_search(query, lang=GOOGLE_PLAY_LANG, country=GOOGLE_PLAY_COUNTRY, n_hits=GOOGLE_PLAY_SEARCH_LIMIT)
        for item in results:
            if not is_google_play_game_candidate(item):
                continue
            if not (
                match_developer_id(item.get("developerId") or item.get("developer_id"), [identifier])
                or match_developer_name(item.get("developer"), [identifier])
            ):
                continue
            app_id = item.get("appId") or item.get("app_id")
            if app_id and app_id not in matched_app_ids:
                matched_app_ids.append(app_id)

    apps: list[dict[str, Any]] = []
    for app_id in matched_app_ids:
        details = gp_app(app_id, lang=GOOGLE_PLAY_LANG, country=GOOGLE_PLAY_COUNTRY)
        details["appId"] = app_id
        apps.append(details)
    return apps


def audit_identifier(target: dict[str, Any], identifier: str) -> dict[str, Any]:
    if target["store"] == "app_store":
        apps = fetch_app_store_apps_for_identifier(target, identifier)
        game_apps = [app for app in apps if is_app_store_game(app)]
        latest_game_activity = max((parse_app_store_last_activity(app) for app in game_apps), default=None)
    else:
        apps = fetch_google_play_apps_for_identifier(target, identifier)
        game_apps = [app for app in apps if is_google_play_game(app)]
        latest_game_activity = max((parse_google_play_last_activity(app) for app in game_apps), default=None)

    if apps and not game_apps:
        return {
            "identifier": identifier,
            "keep": False,
            "reason": "non_game_account",
            "app_count": len(apps),
            "game_app_count": 0,
            "latest_game_activity": None,
        }

    if not game_apps:
        return {
            "identifier": identifier,
            "keep": False,
            "reason": "no_game_apps_found",
            "app_count": len(apps),
            "game_app_count": 0,
            "latest_game_activity": None,
        }

    if is_stale(latest_game_activity):
        return {
            "identifier": identifier,
            "keep": False,
            "reason": "stale_game_account",
            "app_count": len(apps),
            "game_app_count": len(game_apps),
            "latest_game_activity": latest_game_activity.astimezone(timezone.utc).isoformat() if latest_game_activity else None,
        }

    return {
        "identifier": identifier,
        "keep": True,
        "reason": "active_game_account",
        "app_count": len(apps),
        "game_app_count": len(game_apps),
        "latest_game_activity": latest_game_activity.astimezone(timezone.utc).isoformat() if latest_game_activity else None,
    }


def prune_target(target: dict[str, Any], audit_results: list[dict[str, Any]]) -> dict[str, Any] | None:
    kept_identifiers = [result["identifier"] for result in audit_results if result.get("keep")]
    if not kept_identifiers:
        return None

    pruned_target = dict(target)
    if target["store"] == "app_store":
        pruned_target["developer_ids"] = kept_identifiers
    else:
        kept_text_ids = [identifier for identifier in kept_identifiers if not identifier.isdigit()]
        pruned_target["developer_ids"] = kept_identifiers
        pruned_target["developer_names"] = [target["label"], *[name for name in kept_text_ids if name != target["label"]]]
    return pruned_target


def audit_core_developers(targets: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    trimmed_targets: list[dict[str, Any]] = []
    report_targets: list[dict[str, Any]] = []

    for target in targets:
        identifiers = build_identifier_candidates(target)
        audit_results = [audit_identifier(target, identifier) for identifier in identifiers]
        pruned = prune_target(target, audit_results)
        if pruned is not None:
            trimmed_targets.append(pruned)
        report_targets.append(
            {
                "label": target["label"],
                "store": target["store"],
                "kept_count": len([result for result in audit_results if result.get("keep")]),
                "removed_count": len([result for result in audit_results if not result.get("keep")]),
                "results": audit_results,
            }
        )

    summary = {
        "target_count_before": len(targets),
        "target_count_after": len(trimmed_targets),
        "removed_identifier_count": sum(target["removed_count"] for target in report_targets),
        "targets": report_targets,
    }
    return trimmed_targets, summary


def save_json(path: Path, payload: Any) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def main(argv: list[str]) -> int:
    input_path = Path(argv[1]) if len(argv) > 1 else CORE_DEVELOPERS_PATH
    output_path = Path(argv[2]) if len(argv) > 2 else TRIMMED_CORE_DEVELOPERS_PATH
    report_path = Path(argv[3]) if len(argv) > 3 else AUDIT_REPORT_PATH

    if not input_path.exists():
        print(f"[Error] Input file not found: {input_path}")
        return 1

    try:
        targets = load_core_developers(input_path)
        trimmed_targets, report = audit_core_developers(targets)
        save_json(output_path, trimmed_targets)
        save_json(report_path, report)
    except Exception as exc:
        print(f"[Error] Failed to audit developer accounts: {exc}")
        return 1

    print(f"[OK] Saved trimmed targets to {output_path}")
    print(f"[OK] Saved audit report to {report_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
