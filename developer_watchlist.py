from __future__ import annotations

import asyncio
import json
import time
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
DISCOVERY_COUNTRIES = ["sg", "ca", "au", "hk", "tw"]
EXPANSION_COUNTRIES = ["ph", "my", "id", "nz", "us"]
DEFAULT_SCAN_MODE = "quick"
CACHE_TTL_SECONDS = 6 * 60 * 60
REQUEST_TIMEOUT = 30
CORE_DEVELOPERS_PATH = Path(__file__).with_name("core_developers.json")
TAG_FIELDS = ["company_region", "company_type", "company_scale", "watch_priority"]
RANK_FIELD = "publisher_rank"

_REQUEST_CACHE: dict[tuple[Any, ...], tuple[float, Any]] = {}


def get_cache_value(key: tuple[Any, ...]) -> Any | None:
    cached = _REQUEST_CACHE.get(key)
    if not cached:
        return None
    expires_at, value = cached
    if expires_at < time.time():
        _REQUEST_CACHE.pop(key, None)
        return None
    return value


def set_cache_value(key: tuple[Any, ...], value: Any, ttl_seconds: int = CACHE_TTL_SECONDS) -> Any:
    _REQUEST_CACHE[key] = (time.time() + ttl_seconds, value)
    return value


def cached_requests_json(url: str, *, timeout: int = REQUEST_TIMEOUT) -> dict[str, Any]:
    key = ("requests_json", url)
    cached = get_cache_value(key)
    if cached is not None:
        return cached
    response = requests.get(url, timeout=timeout)
    response.raise_for_status()
    return set_cache_value(key, response.json())


def cached_google_play_search(query: str, country: str) -> list[dict[str, Any]]:
    if gp_search is None:
        raise RuntimeError("google-play-scraper is not installed.")
    key = ("gp_search", query.casefold(), country, GOOGLE_PLAY_LANG, GOOGLE_PLAY_SEARCH_LIMIT)
    cached = get_cache_value(key)
    if cached is not None:
        return cached
    results = gp_search(
        query,
        lang=GOOGLE_PLAY_LANG,
        country=country,
        n_hits=GOOGLE_PLAY_SEARCH_LIMIT,
    )
    return set_cache_value(key, results)


def cached_google_play_app(app_id: str, country: str) -> dict[str, Any]:
    if gp_app is None:
        raise RuntimeError("google-play-scraper is not installed.")
    key = ("gp_app", app_id, country, GOOGLE_PLAY_LANG)
    cached = get_cache_value(key)
    if cached is not None:
        return cached
    details = gp_app(app_id, lang=GOOGLE_PLAY_LANG, country=country)
    return set_cache_value(key, details)


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


def resolve_scan_countries(
    countries: list[str] | None = None,
    scan_mode: str = DEFAULT_SCAN_MODE,
) -> tuple[list[str], list[str], list[str]]:
    normalized = normalize_country_codes(countries)
    discovery_defaults = [country for country in DISCOVERY_COUNTRIES if country in normalized]
    if not discovery_defaults:
        discovery_defaults = normalized[: min(len(normalized), 5)]
    if scan_mode == "full":
        expansion = [country for country in normalized if country not in discovery_defaults]
        return discovery_defaults, expansion, discovery_defaults + expansion
    return discovery_defaults, [], discovery_defaults


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
    *,
    scan_mode: str = DEFAULT_SCAN_MODE,
) -> list[dict[str, Any]]:
    if gp_search is None or gp_app is None:
        raise RuntimeError("google-play-scraper is not installed.")

    query = target["query"]
    discovery_countries, expansion_countries, all_countries = resolve_scan_countries(countries, scan_mode)

    candidates: dict[str, dict[str, Any]] = {}
    for country in discovery_countries:
        results = cached_google_play_search(query, country)
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
            existing = candidates.setdefault(
                app_id,
                {
                    "search_item": item,
                    "discovery_country": country,
                    "observed_countries": [],
                },
            )
            if country not in existing["observed_countries"]:
                existing["observed_countries"].append(country)

    apps: list[dict[str, Any]] = []
    for app_id, candidate in candidates.items():
        discovery_country = candidate["discovery_country"]
        item = candidate["search_item"]
        details = cached_google_play_app(app_id, discovery_country)
        released_at = parse_google_play_release_date(details)
        observed_countries = list(candidate["observed_countries"])

        if scan_mode == "full":
            for country in expansion_countries:
                try:
                    cached_google_play_app(app_id, country)
                    if country not in observed_countries:
                        observed_countries.append(country)
                except Exception:
                    continue

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
            "source_country": discovery_country,
            "observed_countries": observed_countries,
            "first_observed_country": discovery_country,
            "seen_in_us": "us" in observed_countries,
        }
        apps.append(enrich_monitored_app(app, target))

    return merge_monitored_apps(apps, all_countries)


def fetch_app_store_developer_apps(
    target: dict[str, Any],
    countries: list[str] | None = None,
    *,
    scan_mode: str = DEFAULT_SCAN_MODE,
) -> list[dict[str, Any]]:
    discovery_countries, expansion_countries, all_countries = resolve_scan_countries(countries, scan_mode)
    term = quote_plus(target["query"])

    candidates: dict[str, dict[str, Any]] = {}
    for country in discovery_countries:
        url = APP_STORE_SEARCH_URL_TEMPLATE.format(
            term=term,
            country=country,
            limit=APP_STORE_SEARCH_LIMIT,
        )
        payload = cached_requests_json(url)
        for item in payload.get("results", []):
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
            existing = candidates.setdefault(
                app_id,
                {
                    "base_item": item,
                    "discovery_country": country,
                    "observed_countries": [],
                },
            )
            if country not in existing["observed_countries"]:
                existing["observed_countries"].append(country)

    if scan_mode == "full" and candidates:
        wanted_ids = set(candidates.keys())
        for country in expansion_countries:
            url = APP_STORE_SEARCH_URL_TEMPLATE.format(
                term=term,
                country=country,
                limit=APP_STORE_SEARCH_LIMIT,
            )
            payload = cached_requests_json(url)
            for item in payload.get("results", []):
                app_id = str(item.get("trackId"))
                if app_id not in wanted_ids:
                    continue
                if not is_app_store_game_candidate(item):
                    continue
                if not matches_target(
                    item,
                    name_field="artistName",
                    id_fields=["artistId", "artist_id", "sellerId", "seller_id"],
                    target=target,
                ):
                    continue
                if country not in candidates[app_id]["observed_countries"]:
                    candidates[app_id]["observed_countries"].append(country)

    apps: list[dict[str, Any]] = []
    for app_id, candidate in candidates.items():
        item = candidate["base_item"]
        discovery_country = candidate["discovery_country"]
        released_at = parse_app_store_release_date(item)
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
            "source_country": discovery_country,
            "observed_countries": list(candidate["observed_countries"]),
            "first_observed_country": discovery_country,
            "seen_in_us": "us" in candidate["observed_countries"],
        }
        apps.append(enrich_monitored_app(app, target))

    return merge_monitored_apps(apps, all_countries)


def fetch_apps_for_target(
    target: dict[str, Any],
    countries: list[str] | None = None,
    *,
    scan_mode: str = DEFAULT_SCAN_MODE,
) -> list[dict[str, Any]]:
    if target["store"] == "google_play":
        return fetch_google_play_developer_apps(target, countries=countries, scan_mode=scan_mode)
    if target["store"] == "app_store":
        return fetch_app_store_developer_apps(target, countries=countries, scan_mode=scan_mode)
    raise ValueError(f"Unsupported store: {target['store']}")


def monitor_core_developers(
    targets: list[dict[str, Any]] | None = None,
    *,
    countries: list[str] | None = None,
    scan_mode: str = DEFAULT_SCAN_MODE,
) -> dict[str, Any]:
    watch_targets = targets or CORE_DEVELOPERS
    discovery_countries, expansion_countries, active_countries = resolve_scan_countries(countries, scan_mode)
    discovered_apps: list[dict[str, Any]] = []
    target_summaries: list[dict[str, Any]] = []

    for target in watch_targets:
        try:
            apps = fetch_apps_for_target(target, countries=active_countries, scan_mode=scan_mode)
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
        "countries": active_countries,
        "discovery_countries": discovery_countries,
        "expansion_countries": expansion_countries,
        "scan_mode": scan_mode,
    }


def monitor_core_developers_fast(
    targets: list[dict[str, Any]] | None = None,
    *,
    concurrency: int = 10,
    countries: list[str] | None = None,
    scan_mode: str = DEFAULT_SCAN_MODE,
) -> dict[str, Any]:
    watch_targets = targets or CORE_DEVELOPERS
    _, _, active_countries = resolve_scan_countries(countries, scan_mode)
    try:
        from async_monitoring import monitor_targets_async
        return asyncio.run(
            monitor_targets_async(
                watch_targets,
                concurrency=concurrency,
                countries=active_countries,
                scan_mode=scan_mode,
            )
        )
    except Exception:
        return monitor_core_developers(watch_targets, countries=active_countries, scan_mode=scan_mode)


def extract_monitored_app_ids(apps: list[dict[str, Any]]) -> list[str]:
    return [f"{app['store']}::{app['app_id']}" for app in apps if app.get("app_id")]
