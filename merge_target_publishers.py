from __future__ import annotations

import json
import sys
from pathlib import Path


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


def merge_store_bucket(base_store: dict[str, object], incoming_store: dict[str, object]) -> dict[str, object]:
    base_rank = normalize_rank(base_store.get("top"))
    incoming_rank = normalize_rank(incoming_store.get("top"))
    if base_rank is None:
        merged_rank = incoming_rank
    elif incoming_rank is None:
        merged_rank = base_rank
    else:
        merged_rank = min(base_rank, incoming_rank)

    return {
        "ios_ids": dedupe_preserve_order(list(base_store.get("ios_ids", [])) + list(incoming_store.get("ios_ids", []))),
        "google_play_ids": dedupe_preserve_order(list(base_store.get("google_play_ids", [])) + list(incoming_store.get("google_play_ids", []))),
        "top": merged_rank,
    }


def merge_target_publishers(
    base: dict[str, dict[str, object]],
    incoming: dict[str, dict[str, object]],
) -> dict[str, dict[str, object]]:
    merged = {
        publisher: merge_store_bucket({}, stores)
        for publisher, stores in base.items()
    }

    for publisher, stores in incoming.items():
        bucket = merged.get(publisher, {"ios_ids": [], "google_play_ids": [], "top": None})
        merged[publisher] = merge_store_bucket(bucket, stores)

    return merged


def save_target_publishers(data: dict[str, dict[str, object]], path: Path) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def main(argv: list[str]) -> int:
    if len(argv) < 4:
        print("Usage: python merge_target_publishers.py <base.json> <incoming.json> <output.json>")
        return 1

    base_path = Path(argv[1])
    incoming_path = Path(argv[2])
    output_path = Path(argv[3])

    if not base_path.exists():
        print(f"[Error] Base file not found: {base_path}")
        return 1
    if not incoming_path.exists():
        print(f"[Error] Incoming file not found: {incoming_path}")
        return 1

    try:
        base = load_target_publishers(base_path)
        incoming = load_target_publishers(incoming_path)
        merged = merge_target_publishers(base, incoming)
        save_target_publishers(merged, output_path)
    except Exception as exc:
        print(f"[Error] Failed to merge target publishers: {exc}")
        return 1

    print(f"[OK] Saved {len(merged)} merged publishers to {output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
