from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import quote_plus

import requests

from monitoring_labels import infer_market_signal, resolve_company_tags

try:
    from google_play_scraper import app as gp_app
    from google_play_scraper import search as gp_search
except Exception:
    gp_app = None
    gp_search = None


APP_STORE_SEARCH_URL_TEMPLATE = (
    "https://itunes.apple.com/search?term={term}&country={country}&media=software&entity=software&limit={limit}"
)
GOOGLE_PLAY_COUNTRY = "us"
GOOGLE_PLAY_LANG = "en"
GOOGLE_PLAY_SEARCH_LIMIT = 120
APP_STORE_COUNTRY = "us"
APP_STORE_SEARCH_LIMIT = 200
DEFAULT_MONITOR_COUNTRIES = ["ca", "au", "nz", "sg", "ph", "my", "id", "hk", "tw", "us"]
REQUEST_TIMEOUT = 30
CORE_DEVELOPERS_PATH = Path(__file__).with_name("core_developers.json")
TAG_FIELDS = ["company_region", "company_type", "company_scale", "watch_priority"]
RANK_FIELD = "publisher_rank"


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
                "publisher_rank": target.get("publisher_rank"),
                **tags,
            }
        )
    return normalized_targets


CORE_DEVELOPERS: list[dict[str, Any]] = load_core_developers()


def normalize_text(value: str | None) -> str:
    return (value or "").strip().casefold()


def normalize_name_set(values: list[str]) -> set[str]:
    return {normalize_text(value) for value in values if normalize_text(value)}


def normalize_country_codes(countries: list[str] | None) -> list[str]:
    requested = countries or DEFAULT_MONITOR_COUNTRIES
    normalized: list[str] = []
    seen: set[str] = set()
    for country in requested:
        value = str(country or "").strip().casefold()
        if not value or value in seen:
            continue
        seen.add(value)
        normalized.append(value)
    return normalized or list(DEFAULT_MONITOR_COUNTRIES)


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


def parse_app_store_release_date(item: dict[str, Any]) -> datetime | None:
    value = item.get("releaseDate")
    if not isinstance(value, str) or not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def parse_google_play_release_date(details: dict[str, Any]) -> datetime | None:
    released = details.get("released")
    if not isinstance(released, str) or not released:
        return None

    for fmt in ("%b %d, %Y", "%B %d, %Y"):
        try:
            return datetime.strptime(released, fmt).replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    return None


def serialize_release_date(released_at: datetime | None) -> str | None:
    if released_at is None:
        return None
    return released_at.astimezone(timezone.utc).isoformat()


def merge_monitored_apps(apps: list[dict[str, Any]], country_order: list[str] | None = None) -> list[dict[str, Any]]:
    order = normalize_country_codes(country_order)
    order_index = {country: index for index, country in enumerate(order)}
    merged: dict[tuple[str, str], dict[str, Any]] = {}

    for app in apps:
        key = (str(app.get("store")), str(app.get("app_id")))
        observed = normalize_country_codes(app.get("observed_countries"))
        source_country = str(app.get("source_country") or (observed[0] if observed else "")).casefold()

        if key not in merged:
            merged[key] = {
                **app,
                "observed_countries": observed,
                "source_country": source_country or None,
                "first_observed_country": source_country or None,
                "seen_in_us": "us" in observed,
            }
            continue

        existing = merged[key]
        combined = normalize_country_codes([*existing.get("observed_countries", []), *observed])
        existing["observed_countries"] = combined
        existing["seen_in_us"] = "us" in combined

        current_first = str(existing.get("first_observed_country") or "").casefold()
        candidate_countries = [country for country in [current_first, source_country] if country]
        if candidate_countries:
            existing["first_observed_country"] = min(
                candidate_countries,
                key=lambda country: order_index.get(country, len(order_index)),
            )
        if not existing.get("source_country") and source_country:
            existing["source_country"] = source_country

    return list(merged.values())


def enrich_monitored_app(base: dict[str, Any], target: dict[str, Any]) -> dict[str, Any]:
    return {
        **base,
        "market_signal": infer_market_signal(
            title=base.get("title"),
            description=base.get("summary"),
            url=base.get("url"),
        ),
        **{field: target.get(field) for field in TAG_FIELDS},
        "publisher_rank": target.get("publisher_rank"),
    }


def fetch_google_play_developer_apps(
    target: dict[str, Any],
    countries: list[str] | None = None,
) -> list[dict[str, Any]]:
    if gp_search is None or gp_app is None:
        raise RuntimeError("google-play-scraper is not installed.")

    query = target["query"]
    monitor_countries = normalize_country_codes(countries)

    apps: list[dict[str, Any]] = []
    for country in monitor_countries:
        results = gp_search(
            query,
            lang=GOOGLE_PLAY_LANG,
            country=country,
            n_hits=GOOGLE_PLAY_SEARCH_LIMIT,
        )
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
            if not app_id:
                continue
            details = gp_app(app_id, lang=GOOGLE_PLAY_LANG, country=country)
            released_at = parse_google_play_release_date(details)
            app = {
                "store": "google_play",
                "developer_label": target["label"],
                "developer_name": details.get("developer") or item.get("developer") or target["label"],
                "developer_id": item.get("developerId") or item.get("developer_id"),
                "app_id": app_id,
                "title": details.get("title") or item.get("title"),
                "url": f"https://play.google.com/store/apps/details?id={app_id}",
                "icon_url": details.get("icon") or item.get("icon"),
                "summary": details.get("description") or item.get("summary"),
                "released_at": serialize_release_date(released_at),
                "score": details.get("score"),
                "ratings": details.get("ratings"),
                "source_country": country,
                "observed_countries": [country],
                "first_observed_country": country,
                "seen_in_us": country == "us",
            }
            apps.append(enrich_monitored_app(app, target))

    return merge_monitored_apps(apps, monitor_countries)


def fetch_app_store_developer_apps(
    target: dict[str, Any],
    countries: list[str] | None = None,
) -> list[dict[str, Any]]:
    monitor_countries = normalize_country_codes(countries)
    term = quote_plus(target["query"])

    apps: list[dict[str, Any]] = []
    for country in monitor_countries:
        url = APP_STORE_SEARCH_URL_TEMPLATE.format(
            term=term,
            country=country,
            limit=APP_STORE_SEARCH_LIMIT,
        )

        response = requests.get(url, timeout=REQUEST_TIMEOUT)
        response.raise_for_status()
        payload = response.json()
        results = payload.get("results", [])

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
            released_at = parse_app_store_release_date(item)
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
                "released_at": serialize_release_date(released_at),
                "score": item.get("averageUserRating"),
                "ratings": item.get("userRatingCount"),
                "source_country": country,
                "observed_countries": [country],
                "first_observed_country": country,
                "seen_in_us": country == "us",
            }
            apps.append(enrich_monitored_app(app, target))

    return merge_monitored_apps(apps, monitor_countries)


def fetch_apps_for_target(
    target: dict[str, Any],
    countries: list[str] | None = None,
) -> list[dict[str, Any]]:
    if target["store"] == "google_play":
        return fetch_google_play_developer_apps(target, countries=countries)
    if target["store"] == "app_store":
        return fetch_app_store_developer_apps(target, countries=countries)
    raise ValueError(f"Unsupported store: {target['store']}")


def monitor_core_developers(
    targets: list[dict[str, Any]] | None = None,
    *,
    countries: list[str] | None = None,
) -> dict[str, Any]:
    watch_targets = targets or CORE_DEVELOPERS
    monitor_countries = normalize_country_codes(countries)
    discovered_apps: list[dict[str, Any]] = []
    target_summaries: list[dict[str, Any]] = []

    for target in watch_targets:
        try:
            apps = fetch_apps_for_target(target, countries=monitor_countries)
            target_summaries.append(
                {
                    "label": target["label"],
                    "store": target["store"],
                    "developer_names": target.get("developer_names", []),
                    "developer_ids": target.get("developer_ids", []),
                    **{field: target.get(field) for field in TAG_FIELDS},
                    "publisher_rank": target.get("publisher_rank"),
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
                    "publisher_rank": target.get("publisher_rank"),
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
        "countries": monitor_countries,
    }


def monitor_core_developers_fast(
    targets: list[dict[str, Any]] | None = None,
    *,
    concurrency: int = 10,
    countries: list[str] | None = None,
) -> dict[str, Any]:
    watch_targets = targets or CORE_DEVELOPERS
    monitor_countries = normalize_country_codes(countries)
    try:
        from async_monitoring import monitor_targets_async
        return asyncio.run(
            monitor_targets_async(
                watch_targets,
                concurrency=concurrency,
                countries=monitor_countries,
            )
        )
    except Exception:
        return monitor_core_developers(watch_targets, countries=monitor_countries)


def extract_monitored_app_ids(apps: list[dict[str, Any]]) -> list[str]:
    return [f"{app['store']}::{app['app_id']}" for app in apps if app.get("app_id")]
