from __future__ import annotations

import importlib
import json
import os
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

import requests

try:
    from google_play_scraper import app as gp_app
    from google_play_scraper import search as gp_search
except Exception:
    gp_app = None
    gp_search = None


APP_STORE_COUNTRY = "us"
APP_STORE_LIMIT = 10
APP_STORE_GAMES_GENRE_ID = 6014
APP_STORE_TIMEOUT = 20
APP_STORE_RSS_URL = (
    f"https://rss.applemarketingtools.com/api/v2/{APP_STORE_COUNTRY}/apps/"
    f"top-free/{APP_STORE_LIMIT}/apps.json?genre={APP_STORE_GAMES_GENRE_ID}"
)
APP_STORE_LOOKUP_URL_TEMPLATE = (
    "https://itunes.apple.com/lookup?id={app_id}&country={country}"
)
APP_STORE_SOURCE = "top-free-games-genre-6014"

GOOGLE_PLAY_LANG = "en"
GOOGLE_PLAY_COUNTRY = "us"
GOOGLE_PLAY_TARGET_LIMIT = 20
GOOGLE_PLAY_COLLECTION_CANDIDATE_LIMIT = 60
GOOGLE_PLAY_SEARCH_CANDIDATE_LIMIT = 30
GOOGLE_PLAY_SEARCH_KEYWORDS = ["Editor's Choice Games", "Award winning games"]
GOOGLE_PLAY_DEFAULT_SOURCE = "search"
DEFAULT_MAX_GAME_AGE_DAYS = 7


@dataclass
class GameRecord:
    store: str
    app_id: str
    title: str
    developer: str | None
    score: float | None
    ratings: int | None
    icon_url: str | None
    screenshots: list[str]
    description: str | None
    released_at: str | None
    contains_ads: bool | None = None
    offers_iap: bool | None = None
    url: str | None = None
    source: str | None = None
    genre_verified: bool = True

    def to_dict(self) -> dict[str, Any]:
        return {
            "store": self.store,
            "app_id": self.app_id,
            "title": self.title,
            "developer": self.developer,
            "score": self.score,
            "ratings": self.ratings,
            "icon_url": self.icon_url,
            "screenshots": self.screenshots,
            "description": self.description,
            "released_at": self.released_at,
            "contains_ads": self.contains_ads,
            "offers_iap": self.offers_iap,
            "url": self.url,
            "source": self.source,
            "genre_verified": self.genre_verified,
        }


def fetch_json(session: requests.Session, url: str) -> dict[str, Any]:
    response = session.get(url, timeout=APP_STORE_TIMEOUT)
    response.raise_for_status()
    return response.json()


def normalize_app_store_genre_ids(genre_ids: Any) -> set[str]:
    if not isinstance(genre_ids, list):
        return set()
    return {str(genre_id) for genre_id in genre_ids if genre_id is not None}


def parse_app_store_release_date(lookup_item: dict[str, Any]) -> datetime | None:
    for key in ("releaseDate", "currentVersionReleaseDate"):
        value = lookup_item.get(key)
        if not isinstance(value, str) or not value:
            continue
        normalized = value.replace("Z", "+00:00")
        try:
            return datetime.fromisoformat(normalized)
        except ValueError:
            continue
    return None


def parse_google_play_release_date(details: dict[str, Any]) -> datetime | None:
    released = details.get("released")
    if not isinstance(released, str) or not released:
        return None

    for fmt in ("%b %d, %Y", "%B %d, %Y"):
        try:
            parsed = datetime.strptime(released, fmt)
            return parsed.replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    return None


def serialize_release_date(released_at: datetime | None) -> str | None:
    if released_at is None:
        return None
    return released_at.astimezone(timezone.utc).isoformat()


def is_recent_release(
    released_at: datetime | None,
    age_days: int = DEFAULT_MAX_GAME_AGE_DAYS,
    now: datetime | None = None,
) -> bool:
    if released_at is None:
        return False
    current_time = now or datetime.now(timezone.utc)
    threshold = current_time - timedelta(days=age_days)
    return released_at >= threshold


def is_app_store_game(lookup_item: dict[str, Any]) -> bool:
    primary_genre_name = lookup_item.get("primaryGenreName")
    genres = lookup_item.get("genres") or []
    genre_ids = normalize_app_store_genre_ids(lookup_item.get("genreIds"))
    return (
        primary_genre_name == "Games"
        or "Games" in genres
        or str(APP_STORE_GAMES_GENRE_ID) in genre_ids
    )


def fetch_app_store_games(
    age_days: int = DEFAULT_MAX_GAME_AGE_DAYS,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    session = requests.Session()
    session.headers.update(
        {
            "User-Agent": "storescraper/1.0 (+https://itunes.apple.com)",
            "Accept": "application/json",
        }
    )

    payload = fetch_json(session, APP_STORE_RSS_URL)
    results = payload.get("feed", {}).get("results", [])
    games: list[dict[str, Any]] = []

    for item in results:
        app_id = item.get("id")
        if not app_id:
            continue

        lookup_url = APP_STORE_LOOKUP_URL_TEMPLATE.format(
            app_id=app_id, country=APP_STORE_COUNTRY
        )
        lookup_payload = fetch_json(session, lookup_url)
        lookup_results = lookup_payload.get("results", [])
        lookup_item = lookup_results[0] if lookup_results else {}
        released_at = parse_app_store_release_date(lookup_item)
        if not is_app_store_game(lookup_item) or not is_recent_release(released_at, age_days=age_days):
            continue

        record = GameRecord(
            store="app_store",
            app_id=app_id,
            title=item.get("name") or "Unknown",
            developer=item.get("artistName"),
            score=lookup_item.get("averageUserRating"),
            ratings=lookup_item.get("userRatingCount"),
            icon_url=item.get("artworkUrl100"),
            screenshots=lookup_item.get("screenshotUrls", [])[:3],
            description=lookup_item.get("description"),
            released_at=serialize_release_date(released_at),
            url=item.get("url"),
            source=APP_STORE_SOURCE,
            genre_verified=True,
        )
        games.append(record.to_dict())

    metadata = {
        "source": APP_STORE_SOURCE,
        "raw_count": len(results),
        "filtered_count": len(games),
        "max_age_days": age_days,
    }
    return games, metadata


def resolve_google_play_collection_api() -> tuple[Any | None, Any | None]:
    module_names = [
        "google_play_scraper",
        "google_play_scraper.collection",
        "google_play_scraper.features.collection",
    ]

    for module_name in module_names:
        try:
            module = importlib.import_module(module_name)
        except Exception:
            continue

        collection_fn = getattr(module, "collection", None)
        collection_enum = getattr(module, "Collection", None)
        if callable(collection_fn) and collection_enum is not None:
            return collection_fn, collection_enum

    return None, None


def choose_google_play_collection(collection_enum: Any) -> Any | None:
    members = [name for name in dir(collection_enum) if not name.startswith("_")]
    ranked_names: list[str] = []
    ranked_names.extend(
        sorted(name for name in members if "EDITOR" in name and "GAME" in name)
    )
    ranked_names.extend(
        sorted(name for name in members if "EDITOR" in name and name not in ranked_names)
    )
    ranked_names.extend(sorted(name for name in members if name == "NEW_FREE"))
    ranked_names.extend(
        sorted(
            name
            for name in members
            if "NEW" in name and "FREE" in name and name not in ranked_names
        )
    )

    for name in ranked_names:
        return getattr(collection_enum, name, None)

    return None


def normalize_google_play_app_id(item: dict[str, Any]) -> str | None:
    for key in ("appId", "app_id", "app_id_raw"):
        value = item.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def is_google_play_game(details: dict[str, Any]) -> bool:
    genre_id = details.get("genreId")
    if isinstance(genre_id, str) and genre_id.startswith("GAME_"):
        return True

    categories = details.get("categories") or []
    for category in categories:
        if not isinstance(category, dict):
            continue
        category_id = category.get("id")
        if isinstance(category_id, str) and category_id.startswith("GAME_"):
            return True

    return False


def is_recent_google_play_game(
    details: dict[str, Any],
    age_days: int = DEFAULT_MAX_GAME_AGE_DAYS,
    now: datetime | None = None,
) -> bool:
    released_at = parse_google_play_release_date(details)
    return is_recent_release(released_at, age_days=age_days, now=now)


def call_google_play_collection(collection_fn: Any, collection_member: Any) -> list[dict[str, Any]]:
    attempts = [
        lambda: collection_fn(
            collection=collection_member,
            lang=GOOGLE_PLAY_LANG,
            country=GOOGLE_PLAY_COUNTRY,
            results=GOOGLE_PLAY_COLLECTION_CANDIDATE_LIMIT,
        ),
        lambda: collection_fn(
            collection=collection_member,
            lang=GOOGLE_PLAY_LANG,
            country=GOOGLE_PLAY_COUNTRY,
            n_results=GOOGLE_PLAY_COLLECTION_CANDIDATE_LIMIT,
        ),
        lambda: collection_fn(
            collection=collection_member,
            lang=GOOGLE_PLAY_LANG,
            country=GOOGLE_PLAY_COUNTRY,
            count=GOOGLE_PLAY_COLLECTION_CANDIDATE_LIMIT,
        ),
        lambda: collection_fn(
            collection_member,
            lang=GOOGLE_PLAY_LANG,
            country=GOOGLE_PLAY_COUNTRY,
            results=GOOGLE_PLAY_COLLECTION_CANDIDATE_LIMIT,
        ),
        lambda: collection_fn(
            collection_member,
            lang=GOOGLE_PLAY_LANG,
            country=GOOGLE_PLAY_COUNTRY,
        ),
    ]

    last_error: Exception | None = None
    for attempt in attempts:
        try:
            result = attempt()
        except TypeError as exc:
            last_error = exc
            continue

        if isinstance(result, list):
            return result

    if last_error:
        raise last_error

    return []


def dedupe_app_ids(items: list[dict[str, Any]]) -> list[str]:
    app_ids: list[str] = []
    for item in items:
        app_id = normalize_google_play_app_id(item)
        if app_id and app_id not in app_ids:
            app_ids.append(app_id)
    return app_ids


def fetch_google_play_candidates() -> tuple[list[str], str]:
    if gp_search is None:
        raise RuntimeError(
            "google-play-scraper is not installed. Please install dependencies first."
        )

    collection_fn, collection_enum = resolve_google_play_collection_api()
    if collection_fn and collection_enum:
        collection_member = choose_google_play_collection(collection_enum)
        if collection_member is not None:
            items = call_google_play_collection(collection_fn, collection_member)
            app_ids = dedupe_app_ids(items)
            if app_ids:
                source = f"collection:{getattr(collection_member, 'name', collection_member)}"
                return app_ids, source

    for keyword in GOOGLE_PLAY_SEARCH_KEYWORDS:
        items = gp_search(
            keyword,
            n_hits=GOOGLE_PLAY_SEARCH_CANDIDATE_LIMIT,
            lang=GOOGLE_PLAY_LANG,
            country=GOOGLE_PLAY_COUNTRY,
        )
        app_ids = dedupe_app_ids(items)
        if app_ids:
            return app_ids, f"search:{keyword}"

    return [], GOOGLE_PLAY_DEFAULT_SOURCE


def fetch_google_play_games(
    age_days: int = DEFAULT_MAX_GAME_AGE_DAYS,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    if gp_app is None or gp_search is None:
        raise RuntimeError(
            "google-play-scraper is not installed. Please install dependencies first."
        )

    candidate_app_ids, source = fetch_google_play_candidates()
    games: list[dict[str, Any]] = []

    for app_id in candidate_app_ids:
        details = gp_app(app_id, lang=GOOGLE_PLAY_LANG, country=GOOGLE_PLAY_COUNTRY)
        released_at = parse_google_play_release_date(details)
        if not is_google_play_game(details) or not is_recent_release(released_at, age_days=age_days):
            continue

        record = GameRecord(
            store="google_play",
            app_id=app_id,
            title=details.get("title") or "Unknown",
            developer=details.get("developer"),
            score=details.get("score"),
            ratings=details.get("ratings"),
            icon_url=details.get("icon"),
            screenshots=details.get("screenshots", [])[:3],
            description=details.get("description"),
            released_at=serialize_release_date(released_at),
            contains_ads=details.get("containsAds"),
            offers_iap=details.get("offersIAP"),
            url=f"https://play.google.com/store/apps/details?id={app_id}",
            source=source,
            genre_verified=True,
        )
        games.append(record.to_dict())

        if len(games) >= GOOGLE_PLAY_TARGET_LIMIT:
            break

    metadata = {
        "source": source,
        "raw_count": len(candidate_app_ids),
        "filtered_count": len(games),
        "max_age_days": age_days,
    }
    return games, metadata


def heuristic_gameplay_summary(game: dict[str, Any]) -> str:
    description = (game.get("description") or "").replace("\r", " ").replace("\n", " ")
    cleaned = " ".join(description.split())
    if not cleaned:
        return "No gameplay summary is available yet."

    snippets = [part.strip(" -") for part in cleaned.split(".") if part.strip()]
    if not snippets:
        snippets = [cleaned[:120]]

    lead = snippets[0][:90]
    traits: list[str] = []
    lowered = cleaned.lower()
    keyword_pairs = [
        ("multiplayer", "multiplayer potential"),
        ("puzzle", "puzzle loops"),
        ("strategy", "strategy depth"),
        ("idle", "idle progression"),
        ("card", "card-building hooks"),
        ("adventure", "adventure framing"),
        ("simulation", "simulation systems"),
        ("story", "story packaging"),
    ]
    for keyword, label in keyword_pairs:
        if keyword in lowered:
            traits.append(label)
    trait_text = ", ".join(traits[:3]) if traits else "genre cues need manual review"
    return f"{lead}. Core read: {trait_text}."


def call_llm(messages: list[dict[str, str]]) -> str | None:
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        return None

    model = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
    try:
        response = requests.post(
            "https://api.openai.com/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            json={
                "model": model,
                "messages": messages,
                "temperature": 0.7,
            },
            timeout=60,
        )
        response.raise_for_status()
    except requests.RequestException:
        return None

    payload = response.json()
    return payload["choices"][0]["message"]["content"].strip()


def generate_gameplay_summary(game: dict[str, Any]) -> str:
    prompt = (
        "You are a mobile-games editor. Based on the provided metadata, summarize the game's core loop,"
        " theme, and editorial angle in 2 sentences. Do not invent missing details."
    )
    content = json.dumps(
        {
            "title": game.get("title"),
            "developer": game.get("developer"),
            "score": game.get("score"),
            "ratings": game.get("ratings"),
            "description": game.get("description"),
            "released_at": game.get("released_at"),
        },
        ensure_ascii=False,
    )
    result = call_llm(
        [
            {"role": "system", "content": prompt},
            {"role": "user", "content": content},
        ]
    )
    return result or heuristic_gameplay_summary(game)


def fallback_markdown(game: dict[str, Any], summary: str) -> str:
    screenshots = game.get("screenshots") or []
    screenshot_lines = "\n".join(f"![Screenshot {i + 1}]({url})" for i, url in enumerate(screenshots))
    rating_text = f"{game.get('score', 'N/A')} / {game.get('ratings', 'N/A')} ratings"
    monetization: list[str] = []
    if game.get("contains_ads"):
        monetization.append("ads")
    if game.get("offers_iap"):
        monetization.append("IAP")
    monetization_text = ", ".join(monetization) if monetization else "commercial model not explicit"

    return f"""# {game.get('title')}

> Editorial fit: this title is suitable for a new-game watchlist post.

## Hook

{summary}

## Basic info

- Platform: {game.get('store')}
- Developer: {game.get('developer') or 'Unknown'}
- Release date: {game.get('released_at') or 'Unknown'}
- Store rating: {rating_text}
- Monetization: {monetization_text}
- Store link: {game.get('url') or 'N/A'}

## Why it matters

1. It is recent enough to fit a \"new games to watch\" angle.
2. The store page already offers enough visible signals for a first-pass editorial take.
3. Screenshots and description support a quick visual-plus-loop breakdown.

## Draft body

A newly released title worth tracking this week is {game.get('title')}.

Based on the store page, the main hook looks like this: {summary}

For editorial packaging, lead with the premise and core loop first, then add release timing, rating, and monetization, and close on whether the visuals and progression are enough to justify attention right now.

## Image slots

![Icon]({game.get('icon_url') or ''})
{screenshot_lines}
"""


def generate_wechat_markdown(game: dict[str, Any], summary: str) -> str:
    prompt = (
        "You are a games-industry newsletter editor. Write a markdown article draft suitable for a WeChat post"
        " using the provided game metadata. Include a headline, intro, gameplay breakdown, target audience,"
        " editorial verdict, a basic info block, and image placeholders. Do not invent facts."
    )
    content = json.dumps(
        {
            "game": game,
            "summary": summary,
        },
        ensure_ascii=False,
    )
    result = call_llm(
        [
            {"role": "system", "content": prompt},
            {"role": "user", "content": content},
        ]
    )
    return result or fallback_markdown(game, summary)