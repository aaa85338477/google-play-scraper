from __future__ import annotations

import html
import textwrap
from typing import Any

import streamlit as st

import scraper_services as services
from developer_watchlist import CORE_DEVELOPERS, extract_monitored_app_ids, monitor_core_developers
from feishu_bitable import RICH_FIELD_NAMES, sync_game_records_to_bitable
from monitoring_labels import market_signal_label


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
TAG_FIELDS = ["company_region", "company_type", "company_scale", "watch_priority"]
TAG_LABELS = {
    "company_region": "厂商区域",
    "company_type": "厂商类型",
    "company_scale": "厂商体量",
    "watch_priority": "监控优先级",
}
TAG_VALUE_LABELS = {
    "company_region": {"cn": "中国", "jpkr": "日韩", "west": "欧美", "global": "全球/待判定"},
    "company_type": {"publisher": "发行商", "developer": "研发商", "platform": "平台", "indie_studio": "独立工作室"},
    "company_scale": {"head": "头部", "mid": "中型", "small": "小型"},
    "watch_priority": {"p0": "P0 高优先级", "p1": "P1 重点观察", "p2": "P2 常规跟踪"},
}

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


def all_tag_options(field: str) -> list[str]:
    values = sorted({str(target.get(field) or "") for target in CORE_DEVELOPERS if target.get(field)})
    return [value for value in values if value]


for key, default in {
    "games": [],
    "draft_markdown": "",
    "selected_game_id": None,
    "last_source": "",
    "gameplay_summaries": {},
    "status_message": "先从左侧抓取一批候选游戏，或直接运行核心厂商监控。",
    "last_counts": {"raw_count": 0, "filtered_count": 0},
    "age_days": DEFAULT_MAX_GAME_AGE_DAYS,
    "feishu_sync_result": None,
    "monitor_snapshot": None,
    "company_region_filters": all_tag_options("company_region"),
    "company_type_filters": all_tag_options("company_type"),
    "company_scale_filters": all_tag_options("company_scale"),
    "watch_priority_filters": all_tag_options("watch_priority"),
}.items():
    if key not in st.session_state:
        st.session_state[key] = default


def format_tag_value(field: str, value: str | None) -> str:
    mapping = TAG_VALUE_LABELS.get(field, {})
    normalized = str(value or "")
    return mapping.get(normalized, normalized or "未标注")


def score_label(game: dict[str, Any]) -> str:
    score = game.get("score")
    ratings = game.get("ratings")
    score_text = f"{score:.1f}" if isinstance(score, (int, float)) else "暂无"
    ratings_text = f"{ratings:,}" if isinstance(ratings, int) else "暂无"
    return f"评分 {score_text} / 评价 {ratings_text}"


def release_label(game: dict[str, Any]) -> str:
    released_at = game.get("released_at")
    if not released_at:
        return "上线时间未知"
    return f"上线于 {released_at[:10]}"


def company_tag_summary(item: dict[str, Any]) -> str:
    parts = [
        format_tag_value("company_region", item.get("company_region")),
        format_tag_value("company_type", item.get("company_type")),
        format_tag_value("company_scale", item.get("company_scale")),
        format_tag_value("watch_priority", item.get("watch_priority")),
    ]
    return " / ".join(parts)


def ensure_summaries(games: list[dict[str, Any]]) -> None:
    for game in games:
        app_id = game.get("app_id")
        if not app_id or app_id in st.session_state.gameplay_summaries:
            continue
        try:
            summary = generate_gameplay_summary(game)
        except Exception as exc:
            summary = f"玩法摘要生成失败：{exc}"
        st.session_state.gameplay_summaries[app_id] = summary


def reset_selection() -> None:
    st.session_state.selected_game_id = None
    st.session_state.draft_markdown = ""


def update_loaded_games(games: list[dict[str, Any]], metadata: dict[str, Any], label: str) -> None:
    verified_games = [game for game in games if game.get("genre_verified")]
    ensure_summaries(verified_games)
    st.session_state.games = verified_games
    st.session_state.monitor_snapshot = None
    st.session_state.last_source = label
    st.session_state.last_counts = {
        "raw_count": metadata.get("raw_count", 0),
        "filtered_count": metadata.get("filtered_count", len(verified_games)),
    }
    st.session_state.feishu_sync_result = None

    if verified_games:
        st.session_state.status_message = (
            f"已筛出 {len(verified_games)} 款符合条件的游戏，"
            f"发布时间窗口为最近 {metadata.get('max_age_days', st.session_state.age_days)} 天，"
            f"原始候选共 {metadata.get('raw_count', 0)} 个。"
        )
    else:
        st.session_state.status_message = (
            f"当前没有游戏通过“官方游戏分类 + 最近 {metadata.get('max_age_days', st.session_state.age_days)} 天上线”的筛选，"
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
        update_loaded_games(games, metadata, f"Google Play {metadata.get('source', '')}".strip())
    except Exception as exc:
        st.session_state.status_message = f"Google Play 抓取失败：{exc}"


def filtered_monitor_targets() -> list[dict[str, Any]]:
    targets = CORE_DEVELOPERS
    for field in TAG_FIELDS:
        selected_values = st.session_state.get(f"{field}_filters", [])
        if selected_values:
            targets = [target for target in targets if target.get(field) in selected_values]
    return targets


def monitor_watchlist() -> None:
    try:
        targets = filtered_monitor_targets()
        if not targets:
            st.session_state.status_message = "当前筛选条件下没有可监控的厂商目标，请调整左侧标签筛选。"
            return
        with st.spinner("正在扫描核心厂商监控列表..."):
            snapshot = monitor_core_developers(targets)
        st.session_state.monitor_snapshot = snapshot
        st.session_state.games = []
        st.session_state.last_source = "核心厂商监控"
        st.session_state.last_counts = {
            "raw_count": snapshot.get("raw_count", 0),
            "filtered_count": snapshot.get("deduped_count", 0),
        }
        st.session_state.feishu_sync_result = None
        st.session_state.status_message = (
            f"已完成 {len(snapshot.get('targets', []))} 个厂商目标的扫描，"
            f"共发现 {snapshot.get('deduped_count', 0)} 个去重后的应用。"
        )
        reset_selection()
    except Exception as exc:
        st.session_state.status_message = f"核心厂商监控失败：{exc}"


def sync_current_ids_to_feishu() -> None:
    if st.session_state.monitor_snapshot and st.session_state.monitor_snapshot.get("apps"):
        app_ids = extract_monitored_app_ids(st.session_state.monitor_snapshot["apps"])
    else:
        app_ids = [game["app_id"] for game in st.session_state.games if game.get("app_id")]

    if not app_ids:
        st.session_state.status_message = "当前没有可同步的 App_ID，请先抓取结果或运行核心厂商监控。"
        return

    try:
        with st.spinner("正在同步 App_ID 到飞书多维表格..."):
            result = sync_new_app_ids_to_bitable(app_ids)
        st.session_state.feishu_sync_result = result
        if result.get("success"):
            st.session_state.status_message = (
                f"飞书同步完成：新增 {result.get('written_count', 0)} 条 App_ID，"
                f"本次对比得到 {len(result.get('new_app_ids', []))} 个新条目。"
            )
        else:
            st.session_state.status_message = "飞书同步失败，请检查 secrets 配置和飞书应用权限。"
    except Exception as exc:
        st.session_state.feishu_sync_result = {
            "success": False,
            "existing_app_ids": [],
            "new_app_ids": [],
            "written_count": 0,
            "error": str(exc),
        }
        st.session_state.status_message = f"飞书同步失败：{exc}"


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
st.caption("轻量级运营工作台：抓取近期新游、扫描核心厂商、并把历史 App_ID 同步到飞书多维表格。")

left_col, center_col, right_col = st.columns([1.15, 2.25, 1.75], gap="large")

with left_col:
    st.markdown("### 控制栏")
    st.selectbox(
        "时间范围",
        options=AGE_OPTIONS,
        index=AGE_OPTIONS.index(st.session_state.age_days),
        key="age_days",
        format_func=lambda value: f"最近 {value} 天",
    )
    st.markdown("### 厂商筛选")
    for field in TAG_FIELDS:
        options = all_tag_options(field)
        st.multiselect(
            TAG_LABELS[field],
            options=options,
            default=st.session_state.get(f"{field}_filters", options),
            key=f"{field}_filters",
            format_func=lambda value, current_field=field: format_tag_value(current_field, value),
        )
    st.markdown(
        (
            '<div class="sidebar-note">榜单抓取会保留“官方分类明确为游戏”且“最近 N 天内上线”的项目。'
            '厂商监控会先按左侧标签筛出目标厂商，再逐个扫描新包，并为结果动态标注发行信号。</div>'
        ),
        unsafe_allow_html=True,
    )
    if st.button("抓取 App Store 新游", type="primary", width="stretch"):
        load_app_store_games()
    if st.button("抓取 Google Play 新游", width="stretch"):
        load_google_play_games()
    if st.button(f"监控核心厂商（{len(filtered_monitor_targets())} 个目标）", width="stretch"):
        monitor_watchlist()
    if st.button("同步当前 App_ID 到飞书", width="stretch"):
        sync_current_ids_to_feishu()

    st.divider()
    st.markdown("### 当前状态")
    st.info(st.session_state.status_message)
    if st.session_state.last_source:
        st.write(f"数据源：`{st.session_state.last_source}`")
    counts = st.session_state.last_counts
    if counts.get("raw_count"):
        st.write(f"原始候选：`{counts['raw_count']}`")
        st.write(f"最终结果：`{counts['filtered_count']}`")
    if st.session_state.games:
        st.write(f"当前卡片：`{len(st.session_state.games)}`")

    if st.session_state.monitor_snapshot is not None:
        snapshot = st.session_state.monitor_snapshot
        st.divider()
        st.markdown("### 厂商巡检")
        st.write(f"监控目标：`{len(snapshot.get('targets', []))}`")
        st.write(f"发现应用：`{snapshot.get('deduped_count', 0)}`")
        failed_targets = [target for target in snapshot.get("targets", []) if not target.get("success")]
        if failed_targets:
            st.warning(f"有 {len(failed_targets)} 个厂商巡检失败，请展开日志排查。")
        with st.expander("查看监控配置"):
            for target in filtered_monitor_targets()[:80]:
                aliases = "、".join(target.get("developer_names", [])) or "未配置别名"
                developer_ids = "、".join(target.get("developer_ids", [])) or "未配置开发者标识"
                st.markdown(
                    f"- `{target['store']}` / **{target['label']}**\n"
                    f"  标签：{company_tag_summary(target)}\n"
                    f"  查询词：`{target['query']}`\n"
                    f"  名称白名单：{aliases}\n"
                    f"  开发者标识：{developer_ids}"
                )

    if st.session_state.feishu_sync_result is not None:
        sync_result = st.session_state.feishu_sync_result
        st.divider()
        st.markdown("### 飞书同步")
        if sync_result.get("success"):
            st.success(f"已写入 {sync_result.get('written_count', 0)} 条新记录")
        else:
            st.error("同步失败，请检查飞书配置")
        st.write(f"历史记录数：`{len(sync_result.get('existing_app_ids', []))}`")
        st.write(f"本次新增：`{len(sync_result.get('new_app_ids', []))}`")
        if sync_result.get("new_app_ids"):
            st.code("\n".join(sync_result["new_app_ids"][:20]), language="text")

with center_col:
    st.markdown("### 信息流")
    monitor_apps = st.session_state.monitor_snapshot.get("apps", []) if st.session_state.monitor_snapshot else []
    if monitor_apps:
        for app in monitor_apps:
            safe_title = html.escape(app.get("title") or "未知应用")
            safe_developer = html.escape(app.get("developer_name") or "未知开发者")
            safe_store = html.escape(app.get("store") or "")
            safe_summary = html.escape(app.get("summary") or "暂无简介")
            safe_source = html.escape(app.get("developer_label") or "")
            signal_label = market_signal_label(app.get("market_signal"))
            with st.container():
                st.markdown('<div class="panel-card">', unsafe_allow_html=True)
                card_left, card_mid, card_right = st.columns([0.7, 2.2, 1.2], gap="medium")
                with card_left:
                    if app.get("icon_url"):
                        st.image(app["icon_url"], width=92)
                with card_mid:
                    st.markdown(f'<div class="game-title">{safe_title}</div>', unsafe_allow_html=True)
                    st.markdown(
                        f'<div class="game-meta">{safe_developer} · {safe_store} · 监控来源：{safe_source}</div>',
                        unsafe_allow_html=True,
                    )
                    st.caption(f"厂商标签：{company_tag_summary(app)}")
                    st.caption(f"发行信号：{signal_label}")
                    st.markdown(f'<div class="summary-box">{safe_summary}</div>', unsafe_allow_html=True)
                    st.caption(f"监控键：{app['store']}::{app['app_id']}")
                with card_right:
                    if app.get("url"):
                        st.link_button("打开商店页", app["url"], width="stretch")
                st.markdown("</div>", unsafe_allow_html=True)
    elif not st.session_state.games:
        st.markdown(
            '<div class="panel-card">还没有可展示的结果。请先从左侧抓取商店数据，或直接运行“核心厂商监控”。</div>',
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
            signal_label = market_signal_label(game.get("market_signal"))
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
                    st.caption(f"发行信号：{signal_label}")
                    st.markdown(f'<div class="score-chip">{html.escape(score_label(game))}</div>', unsafe_allow_html=True)
                    st.markdown(f'<div class="summary-box">{safe_summary}</div>', unsafe_allow_html=True)
                with card_right:
                    st.write(" ")
                    if st.button("生成推文", key=f"generate_{game['app_id']}", width="stretch"):
                        generate_draft(game)
                    if game.get("url"):
                        st.link_button("打开商店页", game["url"], width="stretch")
                    screenshots = game.get("screenshots") or []
                    if screenshots:
                        st.caption("截图预览")
                        st.image(screenshots[0], width="stretch")
                st.markdown("</div>", unsafe_allow_html=True)

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
            width="stretch",
        )
        st.caption(
            textwrap.dedent(
                """
                提示：如果配置了 `OPENAI_API_KEY`，玩法摘要和推文稿件会调用大模型生成。
                如果没有配置，系统会自动回退到本地摘要和模板稿件。
                `market_signal` 是每次抓取时动态推断的状态信号，不会写死在厂商配置里。
                """
            ).strip()
        )

