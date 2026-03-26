from __future__ import annotations

import html
import textwrap
from typing import Any

import streamlit as st
import scraper_services as services


fetch_app_store_games = services.fetch_app_store_games
fetch_google_play_games = services.fetch_google_play_games
generate_gameplay_summary = services.generate_gameplay_summary
generate_wechat_markdown = services.generate_wechat_markdown
DEFAULT_MAX_GAME_AGE_DAYS = getattr(
    services,
    "DEFAULT_MAX_GAME_AGE_DAYS",
    getattr(services, "MAX_GAME_AGE_DAYS", 7),
)

AGE_OPTIONS = [1, 3, 7, 14]

st.set_page_config(page_title="新游选题台", page_icon=":video_game:", layout="wide")

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
    "status_message": "先从左侧抓一批候选游戏，再挑适合跟进的新游题材。",
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
    return f"评分 {score_text} / 评价 {ratings_text}"



def release_label(game: dict[str, Any]) -> str:
    released_at = game.get("released_at")
    if not released_at:
        return "上线时间未知"
    return f"上线于 {released_at[:10]}"



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
            f"已筛出 {metadata.get('filtered_count', 0)} 款符合条件的新游，"
            f"发布时间限制为最近 {metadata.get('max_age_days', st.session_state.age_days)} 天，"
            f"原始候选共 {metadata.get('raw_count', 0)} 个。"
        )
    else:
        st.session_state.status_message = (
            f"没有游戏通过“官方游戏分类 + 最近 {metadata.get('max_age_days', st.session_state.age_days)} 天上线”的筛选。"
            f"原始候选共 {metadata.get('raw_count', 0)} 个。"
        )
    reset_selection()



def load_app_store_games() -> None:
    try:
        with st.spinner("正在抓取 App Store 新游..."):
            games, metadata = fetch_app_store_games(age_days=st.session_state.age_days)
        update_loaded_games(games, metadata, "App Store 新游推荐")
    except Exception as exc:
        st.session_state.status_message = f"App Store 抓取失败：{exc}"



def load_google_play_games() -> None:
    try:
        with st.spinner("正在抓取 Google Play 新游..."):
            games, metadata = fetch_google_play_games(age_days=st.session_state.age_days)
        update_loaded_games(games, metadata, f"Google Play {metadata.get('source', '')}")
    except Exception as exc:
        st.session_state.status_message = f"Google Play 抓取失败：{exc}"



def generate_draft(game: dict[str, Any]) -> None:
    summary = st.session_state.gameplay_summaries.get(game["app_id"], "")
    try:
        with st.spinner(f"正在为《{game['title']}》生成稿件..."):
            st.session_state.draft_markdown = generate_wechat_markdown(game, summary)
        st.session_state.selected_game_id = game["app_id"]
        st.session_state.status_message = f"已生成《{game['title']}》的 Markdown 稿件。"
    except Exception as exc:
        st.session_state.status_message = f"稿件生成失败：{exc}"


st.title("新游选题台")
st.caption("一个轻量的运营工作台：抓取近期开服新游，快速浏览，并生成公众号稿件。")

left_col, center_col, right_col = st.columns([1.1, 2.3, 1.7], gap="large")

with left_col:
    st.markdown("### 控制栏")
    st.selectbox(
        "时间范围",
        options=AGE_OPTIONS,
        index=AGE_OPTIONS.index(st.session_state.age_days),
        key="age_days",
        format_func=lambda value: f"最近 {value} 天",
    )
    st.markdown(
        f'<div class="sidebar-note">先抓取商店候选列表，再只保留“官方分类明确是游戏”且“最近 {st.session_state.age_days} 天内上线”的项目。</div>',
        unsafe_allow_html=True,
    )
    if st.button("抓取 App Store 新游", use_container_width=True, type="primary"):
        load_app_store_games()
    if st.button("抓取 Google Play 新游", use_container_width=True):
        load_google_play_games()

    st.divider()
    st.markdown("### 当前状态")
    st.info(st.session_state.status_message)
    if st.session_state.last_source:
        st.write(f"数据源：`{st.session_state.last_source}`")
    counts = st.session_state.last_counts
    if counts.get("raw_count"):
        st.write(f"原始候选：`{counts['raw_count']}`")
        st.write(f"筛出新游：`{counts['filtered_count']}`")
    if st.session_state.games:
        st.write(f"当前卡片：`{len(st.session_state.games)}`")

with center_col:
    st.markdown("### 信息流")
    if not st.session_state.games:
        st.markdown(
            '<div class="panel-card">还没有可展示的新游结果。请先从左侧选择商店抓取；如果这里为空，通常表示候选都没通过“游戏分类 + 上线时间”的严格筛选。</div>',
            unsafe_allow_html=True,
        )
    else:
        for game in st.session_state.games:
            summary = st.session_state.gameplay_summaries.get(game["app_id"], "")
            safe_summary = html.escape(summary)
            safe_title = html.escape(game["title"])
            safe_developer = html.escape(game.get("developer") or "未知开发者")
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
    st.markdown("### 稿件区")
    if st.session_state.selected_game_id:
        selected = next(
            (item for item in st.session_state.games if item["app_id"] == st.session_state.selected_game_id),
            None,
        )
        if selected:
            st.success(f"当前稿件：{selected['title']}")
    else:
        st.warning("在中间选中一张卡片并点击“生成推文”，这里就会出现可编辑的 Markdown 稿件。")

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
                提示：如果配置了 `OPENAI_API_KEY`，玩法摘要和推文稿件会调用大模型。
                如果没有配置，系统会自动回退到本地摘要和模板稿件。
                """
            ).strip()
        )