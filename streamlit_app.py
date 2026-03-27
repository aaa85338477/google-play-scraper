from __future__ import annotations

import html
from datetime import datetime, timedelta, timezone
from typing import Any

import streamlit as st

from developer_watchlist import CORE_DEVELOPERS, monitor_core_developers_fast
from feishu_bitable import RICH_FIELD_NAMES, sync_game_records_to_bitable
from monitoring_labels import market_signal_label

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
DEFAULT_RELEASE_WINDOW_DAYS = 8

st.set_page_config(page_title="核心厂商监控台", page_icon=":video_game:", layout="wide")

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


def parse_iso_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None


def within_release_window(released_at: str | None, days: int) -> bool:
    parsed = parse_iso_datetime(released_at)
    if parsed is None:
        return False
    return parsed >= datetime.now(timezone.utc) - timedelta(days=days)


def all_tag_options(field: str) -> list[str]:
    values = sorted({str(target.get(field) or "") for target in CORE_DEVELOPERS if target.get(field)})
    return [value for value in values if value]


def all_rank_values() -> list[int]:
    return sorted({target["publisher_rank"] for target in CORE_DEVELOPERS if isinstance(target.get("publisher_rank"), int)})


def rank_bounds() -> tuple[int, int]:
    ranks = [rank for rank in all_rank_values() if 1 <= rank <= 150]
    if not ranks:
        return (1, 150)
    return (1, 150)


for key, default in {
    "status_message": "点击左侧“监控核心厂商”，系统会按厂商名单和排名范围扫描双端应用，再按首次上架到商店的时间窗口展示结果。",
    "last_source": "",
    "last_counts": {"raw_count": 0, "filtered_count": 0},
    "monitor_snapshot": None,
    "feishu_sync_result": None,
    "selected_app_id": None,
    "company_region_filters": all_tag_options("company_region"),
    "company_type_filters": all_tag_options("company_type"),
    "company_scale_filters": all_tag_options("company_scale"),
    "watch_priority_filters": all_tag_options("watch_priority"),
    "publisher_rank_range": rank_bounds(),
    "release_window_days": DEFAULT_RELEASE_WINDOW_DAYS,
}.items():
    if key not in st.session_state:
        st.session_state[key] = default


def format_tag_value(field: str, value: str | None) -> str:
    mapping = TAG_VALUE_LABELS.get(field, {})
    normalized = str(value or "")
    return mapping.get(normalized, normalized or "未标注")


def company_tag_summary(item: dict[str, Any]) -> str:
    parts = [
        format_tag_value("company_region", item.get("company_region")),
        format_tag_value("company_type", item.get("company_type")),
        format_tag_value("company_scale", item.get("company_scale")),
        format_tag_value("watch_priority", item.get("watch_priority")),
    ]
    return " / ".join(parts)


def rank_label(item: dict[str, Any]) -> str:
    rank = item.get("publisher_rank")
    return f"Top {rank}" if isinstance(rank, int) else "未标注"


def filtered_monitor_targets() -> list[dict[str, Any]]:
    targets = CORE_DEVELOPERS
    for field in TAG_FIELDS:
        selected_values = st.session_state.get(f"{field}_filters", [])
        if selected_values:
            targets = [target for target in targets if target.get(field) in selected_values]

    min_rank, max_rank = st.session_state.get("publisher_rank_range", rank_bounds())
    return [
        target
        for target in targets
        if isinstance(target.get("publisher_rank"), int) and min_rank <= target["publisher_rank"] <= max_rank
    ]


def target_stats(targets: list[dict[str, Any]]) -> dict[str, int]:
    publisher_count = len({target.get("label") for target in targets if target.get("label")})
    google_play_count = sum(1 for target in targets if target.get("store") == "google_play")
    app_store_count = sum(1 for target in targets if target.get("store") == "app_store")
    return {
        "target_count": len(targets),
        "publisher_count": publisher_count,
        "google_play_count": google_play_count,
        "app_store_count": app_store_count,
    }


def monitor_watchlist() -> None:
    targets = filtered_monitor_targets()
    if not targets:
        st.session_state.status_message = "当前筛选条件下没有可监控的厂商目标，请调整左侧标签、排名范围或首发时间窗口。"
        return

    try:
        with st.spinner("正在扫描核心厂商监控列表..."):
            snapshot = monitor_core_developers_fast(targets, concurrency=10)
            raw_apps = snapshot.get("apps", [])
            filtered_apps = [
                app for app in raw_apps if within_release_window(app.get("released_at"), st.session_state.release_window_days)
            ]
    except Exception as exc:
        st.session_state.status_message = f"核心厂商监控失败：{exc}"
        return

    snapshot["apps"] = filtered_apps
    snapshot["deduped_count"] = len(filtered_apps)
    snapshot["release_window_days"] = st.session_state.release_window_days
    snapshot["raw_detected_count"] = len(raw_apps)

    st.session_state.monitor_snapshot = snapshot
    st.session_state.selected_app_id = None
    st.session_state.feishu_sync_result = None
    st.session_state.last_source = f"核心厂商监控 / 首次上架 {st.session_state.release_window_days} 天内"
    st.session_state.last_counts = {
        "raw_count": snapshot.get("raw_detected_count", 0),
        "filtered_count": snapshot.get("deduped_count", 0),
    }
    min_rank, max_rank = st.session_state.publisher_rank_range
    st.session_state.status_message = (
        f"已完成 {len(snapshot.get('targets', []))} 个厂商目标的扫描，"
        f"排名范围 Top {min_rank} - Top {max_rank}，"
        f"仅展示首次上架到商店时间在最近 {st.session_state.release_window_days} 天内的应用，"
        f"共发现 {snapshot.get('deduped_count', 0)} 个结果。"
    )


def build_feishu_payload() -> list[dict[str, Any]]:
    apps = st.session_state.monitor_snapshot.get("apps", []) if st.session_state.monitor_snapshot else []
    return [
        {**app, "feishu_app_id": f"{app['store']}::{app['app_id']}", "raw_app_id": app.get("app_id")}
        for app in apps
        if app.get("app_id")
    ]


def sync_current_records_to_feishu() -> None:
    game_records = build_feishu_payload()
    if not game_records:
        st.session_state.status_message = "当前没有可同步的监控记录，请先点击“监控核心厂商”。"
        return

    try:
        with st.spinner("正在同步记录到飞书多维表格..."):
            result = sync_game_records_to_bitable(game_records)
    except Exception as exc:
        st.session_state.feishu_sync_result = {
            "success": False,
            "existing_app_ids": [],
            "new_app_ids": [],
            "written_count": 0,
            "field_names": [],
            "error": str(exc),
        }
        st.session_state.status_message = f"飞书同步失败：{exc}"
        return

    st.session_state.feishu_sync_result = result
    if result.get("success"):
        st.session_state.status_message = (
            f"飞书同步完成：新增 {result.get('written_count', 0)} 条记录，"
            f"本次对比得到 {len(result.get('new_app_ids', []))} 个新条目。"
        )
    else:
        st.session_state.status_message = "飞书同步失败，请检查 secrets 配置和飞书应用权限。"


def select_app(app_id: str) -> None:
    st.session_state.selected_app_id = app_id


def current_apps() -> list[dict[str, Any]]:
    return st.session_state.monitor_snapshot.get("apps", []) if st.session_state.monitor_snapshot else []


st.title("核心厂商监控台")
st.caption("运营监控工作台：按厂商名单和排名范围扫描双端应用，并按首次上架到商店的时间窗口展示结果。")

left_col, center_col, right_col = st.columns([1.15, 2.25, 1.75], gap="large")

with left_col:
    st.markdown("### 控制栏")
    st.caption("首发时间窗口可调，范围为最近 1 到 30 天")
    st.markdown("### 厂商筛选")
    rank_min, rank_max = rank_bounds()
    st.slider(
        "排名范围",
        min_value=rank_min,
        max_value=rank_max,
        value=st.session_state.get("publisher_rank_range", (rank_min, rank_max)),
        key="publisher_rank_range",
    )
    st.slider(
        "首次上架窗口（天）",
        min_value=1,
        max_value=30,
        value=st.session_state.get("release_window_days", DEFAULT_RELEASE_WINDOW_DAYS),
        key="release_window_days",
    )
    st.caption("例如选择 8 天，则会展示首次上架到商店时间在最近 8 天内的应用。")
    for field in TAG_FIELDS:
        options = all_tag_options(field)
        st.multiselect(
            TAG_LABELS[field],
            options=options,
            default=st.session_state.get(f"{field}_filters", options),
            key=f"{field}_filters",
            format_func=lambda value, current_field=field: format_tag_value(current_field, value),
        )
    current_target_stats = target_stats(filtered_monitor_targets())
    stat_left, stat_right = st.columns(2)
    with stat_left:
        st.metric("监控目标数", current_target_stats["target_count"])
        st.metric("Google Play 目标", current_target_stats["google_play_count"])
    with stat_right:
        st.metric("覆盖厂商数", current_target_stats["publisher_count"])
        st.metric("App Store 目标", current_target_stats["app_store_count"])
    st.markdown(
        '<div class="sidebar-note">当前页面使用方案三：先按左侧标签和排名筛出目标厂商，再扫描厂商名下应用，并按应用首次上架到商店的时间窗口展示结果。这里的时间口径是商店首发时间，不是工具第一次看到的时间。</div>',
        unsafe_allow_html=True,
    )
    if st.button(f"监控核心厂商（{len(filtered_monitor_targets())} 个目标）", type="primary", width="stretch"):
        monitor_watchlist()
    if st.button("同步当前记录到飞书", width="stretch"):
        sync_current_records_to_feishu()

    st.divider()
    st.markdown("### 当前状态")
    st.info(st.session_state.status_message)
    if st.session_state.last_source:
        st.write(f"数据源：`{st.session_state.last_source}`")
    counts = st.session_state.last_counts
    if counts.get("raw_count"):
        st.write(f"原始检测：`{counts['raw_count']}`")
        st.write(f"窗口结果：`{counts['filtered_count']}`")

    if st.session_state.monitor_snapshot is not None:
        snapshot = st.session_state.monitor_snapshot
        st.divider()
        st.markdown("### 厂商巡检")
        st.write(f"监控目标：`{len(snapshot.get('targets', []))}`")
        st.write(f"原始检测：`{snapshot.get('raw_detected_count', 0)}`")
        st.write(f"窗口结果：`{snapshot.get('deduped_count', 0)}`")
        st.write(f"首发窗口：`最近 {snapshot.get('release_window_days', DEFAULT_RELEASE_WINDOW_DAYS)} 天`")
        st.write(f"当前排名：`Top {st.session_state.publisher_rank_range[0]} - Top {st.session_state.publisher_rank_range[1]}`")
        failed_targets = [target for target in snapshot.get("targets", []) if not target.get("success")]
        if failed_targets:
            st.warning(f"有 {len(failed_targets)} 个厂商巡检失败，请展开日志排查。")
        with st.expander("查看监控配置"):
            for target in filtered_monitor_targets()[:80]:
                aliases = "、".join(target.get("developer_names", [])) or "未配置别名"
                developer_ids = "、".join(target.get("developer_ids", [])) or "未配置开发者标识"
                st.markdown(
                    f"- `{target['store']}` / **{target['label']}** / {rank_label(target)}\n"
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
        st.write(f"当前表头数：`{len(sync_result.get('field_names', []))}`")
        if sync_result.get("field_names"):
            st.caption("当前飞书表头：")
            st.code("\n".join(sync_result["field_names"]), language="text")
        st.caption("推荐补齐表头：")
        st.code("\n".join(RICH_FIELD_NAMES), language="text")

with center_col:
    st.markdown("### 监控结果")
    apps = current_apps()
    if not apps:
        st.markdown(
            '<div class="panel-card">还没有可展示的监控结果。请先点击左侧“监控核心厂商”。</div>',
            unsafe_allow_html=True,
        )
    else:
        for app in apps:
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
                    st.caption(f"厂商排名：{rank_label(app)}")
                    if app.get("released_at"):
                        st.caption(f"首次上架：{app['released_at'][:10]}")
                    st.caption(f"发行信号：{signal_label}")
                    with st.expander("查看商店文案", expanded=False):
                        st.markdown(f'<div class="summary-box">{safe_summary}</div>', unsafe_allow_html=True)
                    st.caption(f"监控键：{app['store']}::{app['app_id']}")
                with card_right:
                    if st.button("查看详情", key=f"select_{app['store']}_{app['app_id']}", width="stretch"):
                        select_app(app["app_id"])
                    if app.get("url"):
                        st.link_button("打开商店页", app["url"], width="stretch")
                st.markdown("</div>", unsafe_allow_html=True)

with right_col:
    st.markdown("### 详情区")
    selected = next((item for item in current_apps() if item.get("app_id") == st.session_state.selected_app_id), None)
    if not selected:
        st.warning("在中间选中一张卡片并点击“查看详情”，这里会显示该应用的完整监控信息。")
    else:
        st.success(f"当前查看：{selected.get('title') or '未知应用'}")
        st.write(f"平台：`{selected.get('store', 'unknown')}`")
        st.write(f"开发者：`{selected.get('developer_name') or '未知'}`")
        st.write(f"厂商排名：`{rank_label(selected)}`")
        if selected.get("released_at"):
            st.write(f"首次上架：`{selected['released_at'][:10]}`")
        st.write(f"发行信号：`{market_signal_label(selected.get('market_signal'))}`")
        st.write(f"厂商标签：`{company_tag_summary(selected)}`")
        if selected.get("url"):
            st.link_button("打开商店详情页", selected["url"], width="stretch")
        st.text_area(
            "应用简介",
            value=selected.get("summary") or "暂无简介",
            height=420,
            label_visibility="collapsed",
            key=f"detail_{selected['store']}_{selected['app_id']}",
        )
        st.caption("飞书同步会优先写完整记录；如果你当前表里只有 `App_ID`，系统也会自动降级为只写这一列。")
