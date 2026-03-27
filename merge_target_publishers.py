from __future__ import annotations

import json
import sys
from pathlib import Path


def normalize_text(value: object) -> str:
    if value is None:
        return ""
    return str(value).strip()


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


def load_target_publishers(path: Path) -> dict[str, dict[str, list[str]]]:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def merge_target_publishers(
    base: dict[str, dict[str, list[str]]],
    incoming: dict[str, dict[str, list[str]]],
) -> dict[str, dict[str, list[str]]]:
    merged = {
        publisher: {
            "ios_ids": dedupe_preserve_order(stores.get("ios_ids", [])),
            "google_play_ids": dedupe_preserve_order(stores.get("google_play_ids", [])),
        }
        for publisher, stores in base.items()
    }

    for publisher, stores in incoming.items():
        bucket = merged.setdefault(publisher, {"ios_ids": [], "google_play_ids": []})
        bucket["ios_ids"] = dedupe_preserve_order(bucket["ios_ids"] + list(stores.get("ios_ids", [])))
        bucket["google_play_ids"] = dedupe_preserve_order(bucket["google_play_ids"] + list(stores.get("google_play_ids", [])))

    return merged


def save_target_publishers(data: dict[str, dict[str, list[str]]], path: Path) -> None:
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
