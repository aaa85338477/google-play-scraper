from __future__ import annotations

import html
import textwrap
from typing import Any

import streamlit as st

from scraper_services import (
    fetch_app_store_games,
    fetch_google_play_games,
    generate_gameplay_summary,
    generate_wechat_markdown,
)


st.set_page_config(page_title="新游选题台", page_icon="🎮", layout="wide")

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
    "status_message": "左侧先抓一批新游，再从中挑适合公众号的题材。",
}.items():
    if key not in st.session_state:
        st.session_state[key] = default



def score_label(game: dict[str, Any]) -> str:
    score = game.get("score")
    ratings = game.get("ratings")
    score_text = f"{score:.1f}" if isinstance(score, (int, float)) else "N/A"
    ratings_text = f"{ratings:,}" if isinstance(ratings, int) else "N/A"
    return f"评分 {score_text} / 评价 {ratings_text}"



def ensure_summaries(games: list[dict[str, Any]]) -> None:
    for game in games:
        if game["app_id"] in st.session_state.gameplay_summaries:
            continue
        try:
            summary = generate_gameplay_summary(game)
        except Exception as exc:
            summary = f"玩法摘要生成失败：{exc}"
        st.session_state.gameplay_summaries[game["app_id"]] = summary



def reset_selection() -> None:
    st.session_state.selected_game_id = None
    st.session_state.draft_markdown = ""



def load_app_store_games() -> None:
    try:
        with st.spinner("正在抓取 App Store 美区新游..."):
            games = fetch_app_store_games()
        ensure_summaries(games)
        st.session_state.games = games
        st.session_state.last_source = "App Store 新游推荐"
        st.session_state.status_message = f"已抓取 {len(games)} 款 App Store 游戏。"
        reset_selection()
    except Exception as exc:
        st.session_state.status_message = f"App Store 抓取失败：{exc}"



def load_google_play_games() -> None:
    try:
        with st.spinner("正在抓取 Google Play 编辑精选 / 新游集合..."):
            games, source = fetch_google_play_games()
        ensure_summaries(games)
        st.session_state.games = games
        st.session_state.last_source = f"Google Play {source}"
        st.session_state.status_message = f"已抓取 {len(games)} 款 Google Play 游戏，来源：{source}。"
        reset_selection()
    except Exception as exc:
        st.session_state.status_message = f"Google Play 抓取失败：{exc}"



def generate_draft(game: dict[str, Any]) -> None:
    summary = st.session_state.gameplay_summaries.get(game["app_id"], "")
    try:
        with st.spinner(f"正在为《{game['title']}》生成公众号稿件..."):
            st.session_state.draft_markdown = generate_wechat_markdown(game, summary)
        st.session_state.selected_game_id = game["app_id"]
        st.session_state.status_message = f"已生成《{game['title']}》的公众号 Markdown 稿件。"
    except Exception as exc:
        st.session_state.status_message = f"推文生成失败：{exc}"


st.title("🎮 新游选题台")
st.caption("把两套爬虫接成一条运营工作流：抓取、扫卡、挑题、出稿。")

left_col, center_col, right_col = st.columns([1.1, 2.3, 1.7], gap="large")

with left_col:
    st.markdown("### 控制栏")
    st.markdown('<div class="sidebar-note">左边负责拉取候选池。默认优先抓公开榜单与集合，再自动做 AI 摘要，方便你快速扫题材。</div>', unsafe_allow_html=True)
    if st.button("抓取 App Store 新游推荐", use_container_width=True, type="primary"):
        load_app_store_games()
    if st.button("抓取 Google Play 编辑精选", use_container_width=True):
        load_google_play_games()

    st.divider()
    st.markdown("### 当前状态")
    st.info(st.session_state.status_message)
    if st.session_state.last_source:
        st.write(f"数据源：`{st.session_state.last_source}`")
    if st.session_state.games:
        st.write(f"候选数：`{len(st.session_state.games)}`")

with center_col:
    st.markdown("### 信息流")
    if not st.session_state.games:
        st.markdown(
            '<div class="panel-card">还没有抓取结果。先从左侧选择一个商店，系统会把游戏卡片和 AI 提炼玩法一并放到这里。</div>',
            unsafe_allow_html=True,
        )
    else:
        for game in st.session_state.games:
            summary = st.session_state.gameplay_summaries.get(game["app_id"], "")
            safe_summary = html.escape(summary)
            safe_title = html.escape(game["title"])
            safe_developer = html.escape(game.get("developer") or "未知开发者")
            with st.container():
                st.markdown('<div class="panel-card">', unsafe_allow_html=True)
                card_left, card_mid, card_right = st.columns([0.7, 2.2, 1.2], gap="medium")
                with card_left:
                    if game.get("icon_url"):
                        st.image(game["icon_url"], width=92)
                with card_mid:
                    st.markdown(f'<div class="game-title">{safe_title}</div>', unsafe_allow_html=True)
                    st.markdown(
                        f'<div class="game-meta">{safe_developer} · {html.escape(game.get("store") or "")}</div>',
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
                    if st.button("生成推文", key=f"generate_{game['app_id']}", use_container_width=True):
                        generate_draft(game)
                    if game.get("url"):
                        st.link_button("打开商店页", game["url"], use_container_width=True)
                    screenshots = game.get("screenshots") or []
                    if screenshots:
                        st.caption("截图预览")
                        st.image(screenshots[0], use_container_width=True)
                st.markdown('</div>', unsafe_allow_html=True)

with right_col:
    st.markdown("### 操作区")
    if st.session_state.selected_game_id:
        selected = next(
            (item for item in st.session_state.games if item["app_id"] == st.session_state.selected_game_id),
            None,
        )
        if selected:
            st.success(f"当前稿件：{selected['title']}")
    else:
        st.warning("选中一张卡片后，这里会出现可直接改写的公众号 Markdown 草稿。")

    st.session_state.draft_markdown = st.text_area(
        "公众号 Markdown",
        value=st.session_state.draft_markdown,
        height=560,
        key="draft_box",
        label_visibility="collapsed",
    )

    if st.session_state.draft_markdown:
        st.download_button(
            "下载 Markdown",
            data=st.session_state.draft_markdown,
            file_name="wechat_game_post.md",
            mime="text/markdown",
            use_container_width=True,
        )
        st.caption(
            textwrap.dedent(
                """
                提示：如果设置了 `OPENAI_API_KEY`，玩法提炼和推文会调用大模型；
                没设置时会自动回退到本地模板，依然能跑通整个工作流。
                """
            ).strip()
        )
