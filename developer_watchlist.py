from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from urllib.parse import quote_plus

import requests

from monitoring_labels import infer_market_signal, resolve_company_tags

try:
    from google_play_scraper import search as gp_search
except Exception:
    gp_search = None


APP_STORE_SEARCH_URL_TEMPLATE = (
    "https://itunes.apple.com/search?term={term}&country={country}&media=software&entity=software&limit={limit}"
)
GOOGLE_PLAY_COUNTRY = "us"
GOOGLE_PLAY_LANG = "en"
GOOGLE_PLAY_SEARCH_LIMIT = 120
APP_STORE_COUNTRY = "us"
APP_STORE_SEARCH_LIMIT = 200
REQUEST_TIMEOUT = 30
CORE_DEVELOPERS_PATH = Path(__file__).with_name("core_developers.json")
TAG_FIELDS = ["company_region", "company_type", "company_scale", "watch_priority"]


def load_core_developers(config_path: Path = CORE_DEVELOPERS_PATH) -> list[dict[str, Any]]:
    with config_path.open("r", encoding="utf-8-sig") as file:
        targets = json.load(file)

    normalized_targets: list[dict[str, Any]] = []
    for target in targets:
        developer_names = [str(name).strip() for name in (target.get("developer_names") or []) if str(name).strip()]
        developer_ids = [str(name).strip() for name in (target.get("developer_ids") or []) if str(name).strip()]
        tags = resolve_company_tags(target.get("label", ""), target)
        normalized_targets.append(
            {
                "store": target["store"],
                "label": target["label"],
                "query": target["query"],
                "developer_names": developer_names,
                "developer_ids": developer_ids,
                **tags,
            }
        )
    return normalized_targets


CORE_DEVELOPERS: list[dict[str, Any]] = load_core_developers()


def normalize_text(value: str | None) -> str:
    return (value or "").strip().casefold()


def normalize_name_set(values: list[str]) -> set[str]:
    return {normalize_text(value) for value in values if normalize_text(value)}


def is_google_play_game_candidate(item: dict[str, Any]) -> bool:
    app_id = item.get("appId") or item.get("app_id")
    title = item.get("title")
    return isinstance(app_id, str) and bool(title)


def is_app_store_game_candidate(item: dict[str, Any]) -> bool:
    track_id = item.get("trackId")
    track_name = item.get("trackName")
    kind = item.get("kind")
    return bool(track_id) and bool(track_name) and kind == "software"


def match_developer_name(candidate_name: str | None, allowed_names: list[str]) -> bool:
    if not allowed_names:
        return True
    return normalize_text(candidate_name) in normalize_name_set(allowed_names)


def match_developer_id(candidate_id: Any, allowed_ids: list[str]) -> bool:
    if not allowed_ids:
        return False
    normalized_candidate = normalize_text(str(candidate_id) if candidate_id is not None else None)
    return bool(normalized_candidate) and normalized_candidate in normalize_name_set(allowed_ids)


def matches_target(item: dict[str, Any], *, name_field: str, id_fields: list[str], target: dict[str, Any]) -> bool:
    allowed_names = target.get("developer_names") or []
    allowed_ids = target.get("developer_ids") or []

    for id_field in id_fields:
        if match_developer_id(item.get(id_field), allowed_ids):
            return True

    return match_developer_name(item.get(name_field), allowed_names)


def enrich_monitored_app(base: dict[str, Any], target: dict[str, Any]) -> dict[str, Any]:
    return {
        **base,
        "market_signal": infer_market_signal(
            title=base.get("title"),
            description=base.get("summary"),
            url=base.get("url"),
        ),
        **{field: target.get(field) for field in TAG_FIELDS},
    }


def fetch_google_play_developer_apps(target: dict[str, Any]) -> list[dict[str, Any]]:
    if gp_search is None:
        raise RuntimeError("google-play-scraper is not installed.")

    query = target["query"]
    results = gp_search(
        query,
        lang=GOOGLE_PLAY_LANG,
        country=GOOGLE_PLAY_COUNTRY,
        n_hits=GOOGLE_PLAY_SEARCH_LIMIT,
    )

    apps: list[dict[str, Any]] = []
    for item in results:
        if not is_google_play_game_candidate(item):
            continue
        if not matches_target(
            item,
            name_field="developer",
            id_fields=["developerId", "developer_id", "developer_id_raw"],
            target=target,
        ):
            continue
        app_id = item.get("appId") or item.get("app_id")
        app = {
            "store": "google_play",
            "developer_label": target["label"],
            "developer_name": item.get("developer") or target["label"],
            "developer_id": item.get("developerId") or item.get("developer_id"),
            "app_id": app_id,
            "title": item.get("title"),
            "url": f"https://play.google.com/store/apps/details?id={app_id}",
            "icon_url": item.get("icon"),
            "summary": item.get("summary"),
        }
        apps.append(enrich_monitored_app(app, target))

    deduped: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for app in apps:
        app_id = app["app_id"]
        if app_id in seen_ids:
            continue
        seen_ids.add(app_id)
        deduped.append(app)
    return deduped


def fetch_app_store_developer_apps(target: dict[str, Any]) -> list[dict[str, Any]]:
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

    apps: list[dict[str, Any]] = []
    for item in results:
        if not is_app_store_game_candidate(item):
            continue
        if not matches_target(
            item,
            name_field="artistName",
            id_fields=["artistId", "artist_id", "sellerId", "seller_id"],
            target=target,
        ):
            continue
        app_id = str(item.get("trackId"))
        app = {
            "store": "app_store",
            "developer_label": target["label"],
            "developer_name": item.get("artistName") or target["label"],
            "developer_id": item.get("artistId") or item.get("sellerId"),
            "app_id": app_id,
            "title": item.get("trackName"),
            "url": item.get("trackViewUrl"),
            "icon_url": item.get("artworkUrl100"),
            "summary": item.get("description"),
        }
        apps.append(enrich_monitored_app(app, target))

    deduped: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for app in apps:
        app_id = app["app_id"]
        if app_id in seen_ids:
            continue
        seen_ids.add(app_id)
        deduped.append(app)
    return deduped


def fetch_apps_for_target(target: dict[str, Any]) -> list[dict[str, Any]]:
    if target["store"] == "google_play":
        return fetch_google_play_developer_apps(target)
    if target["store"] == "app_store":
        return fetch_app_store_developer_apps(target)
    raise ValueError(f"Unsupported store: {target['store']}")


def monitor_core_developers(targets: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    watch_targets = targets or CORE_DEVELOPERS
    discovered_apps: list[dict[str, Any]] = []
    target_summaries: list[dict[str, Any]] = []

    for target in watch_targets:
        try:
            apps = fetch_apps_for_target(target)
            target_summaries.append(
                {
                    "label": target["label"],
                    "store": target["store"],
                    "developer_names": target.get("developer_names", []),
                    "developer_ids": target.get("developer_ids", []),
                    **{field: target.get(field) for field in TAG_FIELDS},
                    "app_count": len(apps),
                    "success": True,
                }
            )
            discovered_apps.extend(apps)
        except Exception as exc:
            target_summaries.append(
                {
                    "label": target["label"],
                    "store": target["store"],
                    "developer_names": target.get("developer_names", []),
                    "developer_ids": target.get("developer_ids", []),
                    **{field: target.get(field) for field in TAG_FIELDS},
                    "app_count": 0,
                    "success": False,
                    "error": str(exc),
                }
            )

    deduped_apps: list[dict[str, Any]] = []
    seen_keys: set[tuple[str, str]] = set()
    for app in discovered_apps:
        key = (app["store"], app["app_id"])
        if key in seen_keys:
            continue
        seen_keys.add(key)
        deduped_apps.append(app)

    return {
        "targets": target_summaries,
        "apps": deduped_apps,
        "raw_count": len(discovered_apps),
        "deduped_count": len(deduped_apps),
    }


def extract_monitored_app_ids(apps: list[dict[str, Any]]) -> list[str]:
    return [f"{app['store']}::{app['app_id']}" for app in apps if app.get("app_id")]
