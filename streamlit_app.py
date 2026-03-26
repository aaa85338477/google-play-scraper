from __future__ import annotations

import html
import textwrap
from typing import Any

import streamlit as st

from scraper_services import (
    DEFAULT_MAX_GAME_AGE_DAYS,
    fetch_app_store_games,
    fetch_google_play_games,
    generate_gameplay_summary,
    generate_wechat_markdown,
)


AGE_OPTIONS = [1, 3, 7, 14]

st.set_page_config(page_title="Game Scout Desk", page_icon=":video_game:", layout="wide")

st.markdown(
    """
    <style>
    .main {
        background:
            radial-gradient(circle at top left, rgba(255, 208, 122, 0.22), transparent 28%),
            radial-gradient(circle at 85% 15%, rgba(103, 190, 255, 0.18), transparent 26%),
            linear-gradient(180deg, #f8f4ec 0%, #f3efe7 100%);
    }
    .stApp {
        color: #1d2433;
    }
    .panel-card {
        background: rgba(255, 255, 255, 0.86);
        border: 1px solid rgba(29, 36, 51, 0.08);
        border-radius: 18px;
        padding: 18px;
        box-shadow: 0 10px 30px rgba(91, 75, 52, 0.08);
        margin-bottom: 16px;
        backdrop-filter: blur(8px);
    }
    .game-title {
        font-size: 1.1rem;
        font-weight: 700;
        color: #17324d;
        margin-bottom: 4px;
    }
    .game-meta {
        color: #5f6b7a;
        font-size: 0.92rem;
        margin-bottom: 8px;
    }
    .score-chip {
        display: inline-block;
        padding: 4px 10px;
        border-radius: 999px;
        background: #17324d;
        color: white;
        font-size: 0.82rem;
        margin-bottom: 10px;
    }
    .summary-box {
        background: #f7f1e7;
        border-radius: 14px;
        padding: 12px;
        color: #41362c;
        font-size: 0.94rem;
        line-height: 1.55;
        min-height: 84px;
    }
    .sidebar-note {
        font-size: 0.9rem;
        color: #5d6673;
        line-height: 1.5;
    }
    </style>
    """,
    unsafe_allow_html=True,
)

for key, default in {
    "games": [],
    "draft_markdown": "",
    "selected_game_id": None,
    "last_source": "",
    "gameplay_summaries": {},
    "status_message": "Fetch a batch of titles from the left, then pick the new games worth covering.",
    "last_counts": {"raw_count": 0, "filtered_count": 0},
    "age_days": DEFAULT_MAX_GAME_AGE_DAYS,
}.items():
    if key not in st.session_state:
        st.session_state[key] = default



def score_label(game: dict[str, Any]) -> str:
    score = game.get("score")
    ratings = game.get("ratings")
    score_text = f"{score:.1f}" if isinstance(score, (int, float)) else "N/A"
    ratings_text = f"{ratings:,}" if isinstance(ratings, int) else "N/A"
    return f"Score {score_text} / Ratings {ratings_text}"



def release_label(game: dict[str, Any]) -> str:
    released_at = game.get("released_at")
    if not released_at:
        return "Release unknown"
    return f"Released {released_at[:10]}"



def ensure_summaries(games: list[dict[str, Any]]) -> None:
    for game in games:
        if game["app_id"] in st.session_state.gameplay_summaries:
            continue
        try:
            summary = generate_gameplay_summary(game)
        except Exception as exc:
            summary = f"Gameplay summary failed: {exc}"
        st.session_state.gameplay_summaries[game["app_id"]] = summary



def reset_selection() -> None:
    st.session_state.selected_game_id = None
    st.session_state.draft_markdown = ""



def update_loaded_games(games: list[dict[str, Any]], metadata: dict[str, Any], label: str) -> None:
    ensure_summaries(games)
    st.session_state.games = [game for game in games if game.get("genre_verified")]
    st.session_state.last_source = label
    st.session_state.last_counts = {
        "raw_count": metadata.get("raw_count", 0),
        "filtered_count": metadata.get("filtered_count", 0),
    }
    if st.session_state.games:
        st.session_state.status_message = (
            f"Verified {metadata.get('filtered_count', 0)} game apps released within "
            f"{metadata.get('max_age_days', st.session_state.age_days)} days from "
            f"{metadata.get('raw_count', 0)} candidates."
        )
    else:
        st.session_state.status_message = (
            f"No titles passed the strict game + {metadata.get('max_age_days', st.session_state.age_days)}-day filter. "
            f"Raw candidates: {metadata.get('raw_count', 0)}."
        )
    reset_selection()



def load_app_store_games() -> None:
    try:
        with st.spinner("Fetching App Store titles..."):
            games, metadata = fetch_app_store_games(age_days=st.session_state.age_days)
        update_loaded_games(games, metadata, "App Store new game feed")
    except Exception as exc:
        st.session_state.status_message = f"App Store fetch failed: {exc}"



def load_google_play_games() -> None:
    try:
        with st.spinner("Fetching Google Play titles..."):
            games, metadata = fetch_google_play_games(age_days=st.session_state.age_days)
        update_loaded_games(games, metadata, f"Google Play {metadata.get('source', '')}")
    except Exception as exc:
        st.session_state.status_message = f"Google Play fetch failed: {exc}"



def generate_draft(game: dict[str, Any]) -> None:
    summary = st.session_state.gameplay_summaries.get(game["app_id"], "")
    try:
        with st.spinner(f"Generating article draft for {game['title']}..."):
            st.session_state.draft_markdown = generate_wechat_markdown(game, summary)
        st.session_state.selected_game_id = game["app_id"]
        st.session_state.status_message = f"Draft ready for {game['title']}."
    except Exception as exc:
        st.session_state.status_message = f"Draft generation failed: {exc}"


st.title("Game Scout Desk")
st.caption("A lightweight workflow for fetching recent game apps, reviewing them, and drafting article copy.")

left_col, center_col, right_col = st.columns([1.1, 2.3, 1.7], gap="large")

with left_col:
    st.markdown("### Controls")
    st.selectbox(
        "Release window",
        options=AGE_OPTIONS,
        index=AGE_OPTIONS.index(st.session_state.age_days),
        key="age_days",
        format_func=lambda value: f"Last {value} day{'s' if value > 1 else ''}",
    )
    st.markdown(
        f'<div class="sidebar-note">Use the buttons below to load raw candidates, then keep only items verified as games and released within the last {st.session_state.age_days} days.</div>',
        unsafe_allow_html=True,
    )
    if st.button("Fetch App Store Games", use_container_width=True, type="primary"):
        load_app_store_games()
    if st.button("Fetch Google Play Games", use_container_width=True):
        load_google_play_games()

    st.divider()
    st.markdown("### Status")
    st.info(st.session_state.status_message)
    if st.session_state.last_source:
        st.write(f"Source: `{st.session_state.last_source}`")
    counts = st.session_state.last_counts
    if counts.get("raw_count"):
        st.write(f"Raw candidates: `{counts['raw_count']}`")
        st.write(f"Verified new games: `{counts['filtered_count']}`")
    if st.session_state.games:
        st.write(f"Cards shown: `{len(st.session_state.games)}`")

with center_col:
    st.markdown("### Feed")
    if not st.session_state.games:
        st.markdown(
            '<div class="panel-card">No verified recent games to show yet. Fetch a store from the left. If every candidate is filtered out, this panel stays empty on purpose.</div>',
            unsafe_allow_html=True,
        )
    else:
        for game in st.session_state.games:
            summary = st.session_state.gameplay_summaries.get(game["app_id"], "")
            safe_summary = html.escape(summary)
            safe_title = html.escape(game["title"])
            safe_developer = html.escape(game.get("developer") or "Unknown developer")
            safe_store = html.escape(game.get("store") or "")
            safe_release = html.escape(release_label(game))
            with st.container():
                st.markdown('<div class="panel-card">', unsafe_allow_html=True)
                card_left, card_mid, card_right = st.columns([0.7, 2.2, 1.2], gap="medium")
                with card_left:
                    if game.get("icon_url"):
                        st.image(game["icon_url"], width=92)
                with card_mid:
                    st.markdown(f'<div class="game-title">{safe_title}</div>', unsafe_allow_html=True)
                    st.markdown(
                        f'<div class="game-meta">{safe_developer} · {safe_store} · {safe_release}</div>',
                        unsafe_allow_html=True,
                    )
                    st.markdown(
                        f'<div class="score-chip">{html.escape(score_label(game))}</div>',
                        unsafe_allow_html=True,
                    )
                    st.markdown(
                        f'<div class="summary-box">{safe_summary}</div>',
                        unsafe_allow_html=True,
                    )
                with card_right:
                    st.write(" ")
                    if st.button("Generate Draft", key=f"generate_{game['app_id']}", use_container_width=True):
                        generate_draft(game)
                    if game.get("url"):
                        st.link_button("Open Store Page", game["url"], use_container_width=True)
                    screenshots = game.get("screenshots") or []
                    if screenshots:
                        st.caption("Screenshot preview")
                        st.image(screenshots[0], use_container_width=True)
                st.markdown('</div>', unsafe_allow_html=True)

with right_col:
    st.markdown("### Draft")
    if st.session_state.selected_game_id:
        selected = next(
            (item for item in st.session_state.games if item["app_id"] == st.session_state.selected_game_id),
            None,
        )
        if selected:
            st.success(f"Current draft: {selected['title']}")
    else:
        st.warning("Pick a card and generate a draft to populate this panel.")

    st.session_state.draft_markdown = st.text_area(
        "Article Markdown",
        value=st.session_state.draft_markdown,
        height=560,
        key="draft_box",
        label_visibility="collapsed",
    )

    if st.session_state.draft_markdown:
        st.download_button(
            "Download Markdown",
            data=st.session_state.draft_markdown,
            file_name="wechat_game_post.md",
            mime="text/markdown",
            use_container_width=True,
        )
        st.caption(
            textwrap.dedent(
                """
                Tip: if OPENAI_API_KEY is configured, gameplay summaries and article drafts use the model.
                Without a key, the app falls back to local summaries and a template draft.
                """
            ).strip()
        )