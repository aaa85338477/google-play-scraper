from __future__ import annotations

from typing import Any

DEFAULT_COMPANY_TAGS = {
    "company_region": "global",
    "company_type": "publisher",
    "company_scale": "mid",
    "watch_priority": "p2",
}

COMPANY_TAG_OVERRIDES: dict[str, dict[str, str]] = {
    "tencent": {
        "company_region": "cn",
        "company_type": "publisher",
        "company_scale": "head",
        "watch_priority": "p0",
    },
    "netease": {
        "company_region": "cn",
        "company_type": "publisher",
        "company_scale": "head",
        "watch_priority": "p0",
    },
    "supercell": {
        "company_region": "west",
        "company_type": "developer",
        "company_scale": "head",
        "watch_priority": "p0",
    },
    "cognosphere": {
        "company_region": "cn",
        "company_type": "developer",
        "company_scale": "head",
        "watch_priority": "p0",
    },
    "mihoyo": {
        "company_region": "cn",
        "company_type": "developer",
        "company_scale": "head",
        "watch_priority": "p0",
    },
    "devolver": {
        "company_region": "west",
        "company_type": "publisher",
        "company_scale": "mid",
        "watch_priority": "p1",
    },
    "playrix": {
        "company_region": "global",
        "company_type": "publisher",
        "company_scale": "head",
        "watch_priority": "p1",
    },
    "scopely": {
        "company_region": "west",
        "company_type": "publisher",
        "company_scale": "head",
        "watch_priority": "p1",
    },
}

TEST_BUILD_KEYWORDS = [
    "beta",
    "alpha",
    "test build",
    "testflight",
    "cbt",
    "beta test",
    "封测",
    "测试服",
    "体验服",
    "先行服",
]
PRE_REGISTER_KEYWORDS = [
    "pre-register",
    "preregister",
    "pre register",
    "pre-order",
    "pre order",
    "coming soon",
    "wishlist",
    "预注册",
    "预约",
    "即将上线",
]
SOFT_LAUNCH_KEYWORDS = [
    "early access",
    "soft launch",
    "soft-launch",
    "limited release",
    "regional launch",
    "灰度",
    "限区",
    "小范围上线",
]


def normalize_text(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def slugify_label(label: str) -> str:
    lowered = normalize_text(label).casefold()
    return lowered.replace(" ", "")


def resolve_company_tags(label: str, existing: dict[str, Any] | None = None) -> dict[str, str]:
    tags = dict(DEFAULT_COMPANY_TAGS)
    for key, value in (existing or {}).items():
        if key in tags and normalize_text(value):
            tags[key] = normalize_text(value)

    normalized_label = slugify_label(label)
    for alias, override in COMPANY_TAG_OVERRIDES.items():
        if alias in normalized_label:
            tags.update(override)
            break

    return tags


def infer_market_signal(*, title: str | None = None, description: str | None = None, url: str | None = None) -> str:
    haystack = " ".join(part for part in [normalize_text(title), normalize_text(description), normalize_text(url)] if part).casefold()

    for keyword in TEST_BUILD_KEYWORDS:
        if keyword in haystack:
            return "test_build"
    for keyword in PRE_REGISTER_KEYWORDS:
        if keyword in haystack:
            return "pre_register"
    for keyword in SOFT_LAUNCH_KEYWORDS:
        if keyword in haystack:
            return "soft_launch"
    if haystack:
        return "global_launch"
    return "unknown"


def market_signal_label(signal: str | None) -> str:
    mapping = {
        "test_build": "测试包",
        "pre_register": "预注册",
        "soft_launch": "小范围上线",
        "global_launch": "正式上线",
        "unknown": "待判定",
    }
    return mapping.get(normalize_text(signal), "待判定")
