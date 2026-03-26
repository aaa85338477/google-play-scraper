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
        return "暂无玩法摘要，建议结合截图和商店页进一步判断。"

    snippets = [part.strip(" -") for part in cleaned.split(".") if part.strip()]
    if not snippets:
        snippets = [cleaned[:120]]

    lead = snippets[0][:90]
    traits: list[str] = []
    lowered = cleaned.lower()
    keyword_pairs = [
        ("multiplayer", "可能有多人协作或对战卖点"),
        ("puzzle", "偏解谜或关卡挑战"),
        ("strategy", "强调策略搭配"),
        ("idle", "带放置成长节奏"),
        ("card", "卡牌构筑元素较明显"),
        ("adventure", "有冒险探索驱动"),
        ("simulation", "偏模拟经营体验"),
        ("story", "剧情包装感较强"),
    ]
    for keyword, label in keyword_pairs:
        if keyword in lowered:
            traits.append(label)
    trait_text = "，".join(traits[:3]) if traits else "题材和循环还需要人工复核"
    return f"{lead}。核心判断：{trait_text}。"


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
        "你是一名手游内容编辑。请根据给定元数据，用简体中文提炼 2 句话，"
        "总结这款游戏的核心玩法、题材卖点和适合传播的角度，不要虚构信息。"
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
    screenshot_lines = "\n".join(f"![截图 {i + 1}]({url})" for i, url in enumerate(screenshots))
    rating_text = f"{game.get('score', 'N/A')} / {game.get('ratings', 'N/A')} 条评价"
    monetization: list[str] = []
    if game.get("contains_ads"):
        monetization.append("含广告")
    if game.get("offers_iap"):
        monetization.append("含内购")
    monetization_text = "、".join(monetization) if monetization else "商业化信息未明确"

    return f"""# {game.get('title')}

> 选题判断：这款游戏适合放进“近期新游观察”类稿件中。

## 一句话看点

{summary}

## 基本信息

- 平台：{game.get('store')}
- 开发者：{game.get('developer') or '未知'}
- 上线时间：{game.get('released_at') or '未知'}
- 商店评分：{rating_text}
- 商业化：{monetization_text}
- 商店链接：{game.get('url') or '暂无'}

## 值得关注的原因

1. 这款产品足够新，适合放进“近几天新游”选题框架里。
2. 商店页已经提供了基本的题材、玩法与视觉信息，足够支撑一版快稿。
3. 可以结合截图做“玩法机制 + 美术风格 + 受众判断”的三段式表达。

## 稿件正文

最近上新的游戏里，值得留意的一款是《{game.get('title')}》。

从商店公开信息看，这款产品最值得优先提炼的卖点是：{summary}

如果要做成公众号稿件，建议第一段先交代题材与核心循环，第二段补上线时间、评分与商业化信息，第三段落到“适合谁玩、是否值得现在就试”。

## 配图建议

![Icon]({game.get('icon_url') or ''})
{screenshot_lines}
"""


def generate_wechat_markdown(game: dict[str, Any], summary: str) -> str:
    prompt = (
        "你是一名游戏行业公众号编辑。请根据提供的游戏元数据，输出一篇适合微信公众号发布的 Markdown 稿件。"
        "内容需要包含：标题、导语、核心玩法拆解、适合什么玩家、编辑点评、基础信息表和配图占位。"
        "请使用简体中文，不要虚构未提供的信息。"
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