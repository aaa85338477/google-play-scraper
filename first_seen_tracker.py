from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

CACHE_PATH = Path(__file__).with_name('monitor_first_seen_cache.json')


def normalize_text(value: Any) -> str:
    if value is None:
        return ''
    return str(value).strip()


def parse_iso_datetime(value: str | None) -> datetime | None:
    normalized = normalize_text(value)
    if not normalized:
        return None
    try:
        return datetime.fromisoformat(normalized.replace('Z', '+00:00'))
    except ValueError:
        return None


def load_first_seen_cache(path: Path = CACHE_PATH) -> dict[str, str]:
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding='utf-8-sig'))
    except (OSError, json.JSONDecodeError):
        return {}
    return {
        normalize_text(key): normalize_text(value)
        for key, value in payload.items()
        if normalize_text(key) and normalize_text(value)
    }


def save_first_seen_cache(first_seen_map: dict[str, str], path: Path = CACHE_PATH) -> None:
    path.write_text(json.dumps(first_seen_map, ensure_ascii=False, indent=2), encoding='utf-8')


def resolve_first_seen_for_apps(
    apps: list[dict[str, Any]],
    known_first_seen: dict[str, str],
    now: datetime | None = None,
) -> tuple[list[dict[str, Any]], dict[str, str]]:
    current_time = now or datetime.now(timezone.utc)
    current_iso = current_time.isoformat()
    resolved_map = dict(known_first_seen)
    resolved_apps: list[dict[str, Any]] = []

    for app in apps:
        app_key = normalize_text(f"{app.get('store')}::{app.get('app_id')}")
        if not app_key:
            resolved_apps.append(dict(app))
            continue
        first_seen_at = normalize_text(resolved_map.get(app_key)) or current_iso
        resolved_map[app_key] = first_seen_at
        resolved_apps.append({**app, 'first_seen_at': first_seen_at})

    return resolved_apps, resolved_map


def is_within_first_seen_window(
    first_seen_at: str | None,
    days: int,
    now: datetime | None = None,
) -> bool:
    parsed = parse_iso_datetime(first_seen_at)
    if parsed is None:
        return False
    current_time = now or datetime.now(timezone.utc)
    threshold = current_time - timedelta(days=days)
    return parsed >= threshold


def filter_apps_by_first_seen_window(
    apps: list[dict[str, Any]],
    days: int,
    now: datetime | None = None,
) -> list[dict[str, Any]]:
    return [app for app in apps if is_within_first_seen_window(app.get('first_seen_at'), days, now=now)]
