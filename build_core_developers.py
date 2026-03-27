from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Any

from monitoring_labels import resolve_company_tags

TARGET_PUBLISHERS_PATH = Path("target_publishers.json")
CORE_DEVELOPERS_PATH = Path("core_developers.json")
DIGITS_ONLY_RE = re.compile(r"^\d+$")


def normalize_text(value: object) -> str:
    if value is None:
        return ""
    return str(value).strip()


def normalize_rank(value: object) -> int | None:
    normalized = normalize_text(value)
    if not normalized:
        return None
    try:
        return int(float(normalized))
    except ValueError:
        return None


def is_text_identifier(value: str) -> bool:
    normalized = normalize_text(value)
    return bool(normalized) and not DIGITS_ONLY_RE.fullmatch(normalized)


def dedupe_preserve_order(values: list[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        normalized = normalize_text(value)
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        result.append(normalized)
    return result


def load_target_publishers(path: Path) -> dict[str, dict[str, object]]:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def build_core_developers(target_publishers: dict[str, dict[str, object]]) -> list[dict[str, Any]]:
    targets: list[dict[str, Any]] = []

    for publisher_name, stores in target_publishers.items():
        label = normalize_text(publisher_name)
        if not label:
            continue

        tags = resolve_company_tags(label)
        publisher_rank = normalize_rank(stores.get("top"))
        ios_ids = dedupe_preserve_order(stores.get("ios_ids", []))
        google_play_ids = dedupe_preserve_order(stores.get("google_play_ids", []))
        google_play_names = [value for value in google_play_ids if is_text_identifier(value)]

        if google_play_ids:
            targets.append(
                {
                    "store": "google_play",
                    "label": label,
                    "query": label,
                    "developer_names": dedupe_preserve_order([label, *google_play_names]),
                    "developer_ids": google_play_ids,
                    "publisher_rank": publisher_rank,
                    **tags,
                }
            )

        if ios_ids:
            targets.append(
                {
                    "store": "app_store",
                    "label": label,
                    "query": label,
                    "developer_names": [label],
                    "developer_ids": ios_ids,
                    "publisher_rank": publisher_rank,
                    **tags,
                }
            )

    return targets


def save_core_developers(targets: list[dict[str, Any]], path: Path) -> None:
    path.write_text(json.dumps(targets, ensure_ascii=False, indent=2), encoding="utf-8")


def main(argv: list[str]) -> int:
    input_path = Path(argv[1]) if len(argv) > 1 else TARGET_PUBLISHERS_PATH
    output_path = Path(argv[2]) if len(argv) > 2 else CORE_DEVELOPERS_PATH

    if not input_path.exists():
        print(f"[Error] Input file not found: {input_path}")
        return 1

    try:
        target_publishers = load_target_publishers(input_path)
        core_developers = build_core_developers(target_publishers)
        save_core_developers(core_developers, output_path)
    except Exception as exc:
        print(f"[Error] Failed to build core developers config: {exc}")
        return 1

    print(f"[OK] Saved {len(core_developers)} monitoring targets to {output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
