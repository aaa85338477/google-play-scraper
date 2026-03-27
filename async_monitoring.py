from __future__ import annotations

import asyncio
from typing import Any
from urllib.parse import quote_plus

import aiohttp

from developer_watchlist import (
    APP_STORE_COUNTRY,
    APP_STORE_SEARCH_LIMIT,
    APP_STORE_SEARCH_URL_TEMPLATE,
    GOOGLE_PLAY_COUNTRY,
    GOOGLE_PLAY_LANG,
    REQUEST_TIMEOUT,
    enrich_monitored_app,
    fetch_google_play_developer_apps,
    is_app_store_game_candidate,
    matches_target,
    parse_app_store_release_date,
    serialize_release_date,
)

DEFAULT_MAX_CONCURRENCY = 10
APP_STORE_MAX_CONCURRENCY = 6
GOOGLE_PLAY_MAX_CONCURRENCY = 4
DEFAULT_RETRIES = 2


async def fetch_json(
    session: aiohttp.ClientSession,
    url: str,
    *,
    timeout_seconds: int = REQUEST_TIMEOUT,
    retries: int = DEFAULT_RETRIES,
) -> dict[str, Any]:
    last_error: Exception | None = None

    for attempt in range(retries + 1):
        try:
            timeout = aiohttp.ClientTimeout(total=timeout_seconds)
            async with session.get(url, timeout=timeout) as response:
                response.raise_for_status()
                return await response.json()
        except (aiohttp.ClientError, asyncio.TimeoutError) as exc:
            last_error = exc
            if attempt >= retries:
                break
            await asyncio.sleep(2**attempt)

    raise RuntimeError(f"Async fetch failed for {url}: {last_error}") from last_error


async def fetch_developer_apps(
    session: aiohttp.ClientSession | None,
    developer_id: str,
    platform: str,
    *,
    target: dict[str, Any] | None = None,
    semaphore: asyncio.Semaphore | None = None,
) -> list[dict[str, Any]]:
    gate = semaphore or asyncio.Semaphore(1)

    async with gate:
        if platform == "app_store":
            if session is None or target is None:
                raise ValueError("App Store async fetch requires session and target.")
            term = quote_plus(target["query"])
            url = APP_STORE_SEARCH_URL_TEMPLATE.format(
                term=term,
                country=APP_STORE_COUNTRY,
                limit=APP_STORE_SEARCH_LIMIT,
            )
            payload = await fetch_json(session, url)
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
                }
                apps.append(enrich_monitored_app(app, target))
            return dedupe_apps(apps)

        if platform == "google_play":
            last_error: Exception | None = None
            for attempt in range(DEFAULT_RETRIES + 1):
                try:
                    return await asyncio.to_thread(fetch_google_play_developer_apps, target or {"query": developer_id})
                except Exception as exc:
                    last_error = exc
                    if attempt >= DEFAULT_RETRIES:
                        break
                    await asyncio.sleep(2**attempt)
            raise RuntimeError(f"Google Play fetch failed for {developer_id}: {last_error}") from last_error

        raise ValueError(f"Unsupported platform: {platform}")


async def run_target(
    session: aiohttp.ClientSession,
    target: dict[str, Any],
    app_store_semaphore: asyncio.Semaphore,
    google_play_semaphore: asyncio.Semaphore,
) -> dict[str, Any]:
    try:
        if target["store"] == "app_store":
            apps = await fetch_developer_apps(
                session,
                target["query"],
                "app_store",
                target=target,
                semaphore=app_store_semaphore,
            )
        elif target["store"] == "google_play":
            apps = await fetch_developer_apps(
                session,
                target["query"],
                "google_play",
                target=target,
                semaphore=google_play_semaphore,
            )
        else:
            raise ValueError(f"Unsupported store: {target['store']}")

        return {
            "label": target["label"],
            "store": target["store"],
            "developer_names": target.get("developer_names", []),
            "developer_ids": target.get("developer_ids", []),
            "company_region": target.get("company_region"),
            "company_type": target.get("company_type"),
            "company_scale": target.get("company_scale"),
            "watch_priority": target.get("watch_priority"),
            "publisher_rank": target.get("publisher_rank"),
            "app_count": len(apps),
            "success": True,
            "apps": apps,
        }
    except Exception as exc:
        return {
            "label": target["label"],
            "store": target["store"],
            "developer_names": target.get("developer_names", []),
            "developer_ids": target.get("developer_ids", []),
            "company_region": target.get("company_region"),
            "company_type": target.get("company_type"),
            "company_scale": target.get("company_scale"),
            "watch_priority": target.get("watch_priority"),
            "publisher_rank": target.get("publisher_rank"),
            "app_count": 0,
            "success": False,
            "error": str(exc),
            "apps": [],
        }


async def monitor_targets_async(
    targets: list[dict[str, Any]],
    *,
    concurrency: int = DEFAULT_MAX_CONCURRENCY,
) -> dict[str, Any]:
    timeout = aiohttp.ClientTimeout(total=REQUEST_TIMEOUT)
    connector = aiohttp.TCPConnector(limit=max(concurrency, 1))
    app_store_semaphore = asyncio.Semaphore(min(concurrency, APP_STORE_MAX_CONCURRENCY))
    google_play_semaphore = asyncio.Semaphore(min(concurrency, GOOGLE_PLAY_MAX_CONCURRENCY))

    async with aiohttp.ClientSession(timeout=timeout, connector=connector) as session:
        task_results = await asyncio.gather(
            *[
                run_target(session, target, app_store_semaphore, google_play_semaphore)
                for target in targets
            ]
        )

    discovered_apps: list[dict[str, Any]] = []
    target_summaries: list[dict[str, Any]] = []
    for result in task_results:
        discovered_apps.extend(result.pop("apps", []))
        target_summaries.append(result)

    deduped_apps = dedupe_apps(discovered_apps)
    return {
        "targets": target_summaries,
        "apps": deduped_apps,
        "raw_count": len(discovered_apps),
        "deduped_count": len(deduped_apps),
        "concurrency": concurrency,
    }


def dedupe_apps(apps: list[dict[str, Any]]) -> list[dict[str, Any]]:
    deduped: list[dict[str, Any]] = []
    seen_keys: set[tuple[str, str]] = set()
    for app in apps:
        key = (str(app.get("store")), str(app.get("app_id")))
        if key in seen_keys:
            continue
        seen_keys.add(key)
        deduped.append(app)
    return deduped
