from __future__ import annotations

import csv
import json
import re
import sys
import zipfile
from pathlib import Path
from typing import Iterator
import xml.etree.ElementTree as ET

EXPECTED_PUBLISHER_FIELD = "publisher_name"
EXPECTED_STORE_ID_FIELD = "store_publisher_id"
EXPECTED_RANK_FIELD = "top"
XLSX_NS = {
    "a": "http://schemas.openxmlformats.org/spreadsheetml/2006/main",
    "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
}
DIGITS_ONLY_RE = re.compile(r"^\d+$")
IOS_ID_MAX_LENGTH = 11


def normalize_text(value: object) -> str:
    if value is None:
        return ""
    return str(value).strip()


def parse_rank(value: object) -> int | None:
    normalized = normalize_text(value)
    if not normalized:
        return None
    try:
        return int(float(normalized))
    except ValueError:
        return None


def classify_store_id(store_id: str) -> str:
    normalized = normalize_text(store_id)
    if not normalized:
        return ""
    if DIGITS_ONLY_RE.fullmatch(normalized) and len(normalized) < 12:
        return "ios_ids"
    return "google_play_ids"


def split_store_publisher_ids(raw_value: object) -> list[str]:
    normalized = normalize_text(raw_value)
    if not normalized:
        return []
    return [part.strip() for part in normalized.split(",") if part.strip()]


def dedupe_preserve_order(values: list[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result


def iter_csv_rows(path: Path) -> Iterator[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            yield {key: normalize_text(value) for key, value in row.items()}


def load_shared_strings(archive: zipfile.ZipFile) -> list[str]:
    if "xl/sharedStrings.xml" not in archive.namelist():
        return []
    root = ET.fromstring(archive.read("xl/sharedStrings.xml"))
    strings: list[str] = []
    for node in root.findall("a:si", XLSX_NS):
        text = "".join(fragment.text or "" for fragment in node.iter("{http://schemas.openxmlformats.org/spreadsheetml/2006/main}t"))
        strings.append(text)
    return strings


def resolve_first_sheet_xml(archive: zipfile.ZipFile) -> str:
    workbook = ET.fromstring(archive.read("xl/workbook.xml"))
    relationships = ET.fromstring(archive.read("xl/_rels/workbook.xml.rels"))
    rel_map = {rel.attrib["Id"]: rel.attrib["Target"] for rel in relationships}
    first_sheet = workbook.find("a:sheets/a:sheet", XLSX_NS)
    if first_sheet is None:
        raise ValueError("Workbook does not contain any sheets.")
    rel_id = first_sheet.attrib["{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id"]
    target = rel_map[rel_id]
    return target if target.startswith("xl/") else f"xl/{target}"


def read_xlsx_rows(path: Path) -> Iterator[dict[str, str]]:
    with zipfile.ZipFile(path) as archive:
        shared_strings = load_shared_strings(archive)
        worksheet_path = resolve_first_sheet_xml(archive)
        worksheet = ET.fromstring(archive.read(worksheet_path))
        rows = worksheet.findall("a:sheetData/a:row", XLSX_NS)
        if not rows:
            return

        headers = read_xlsx_row(rows[0], shared_strings)
        for row in rows[1:]:
            values = read_xlsx_row(row, shared_strings)
            padded_values = values + [""] * max(0, len(headers) - len(values))
            yield {
                header: normalize_text(padded_values[index])
                for index, header in enumerate(headers)
                if header
            }


def read_xlsx_row(row_node: ET.Element, shared_strings: list[str]) -> list[str]:
    values: list[str] = []
    for cell in row_node.findall("a:c", XLSX_NS):
        value_node = cell.find("a:v", XLSX_NS)
        value = ""
        if value_node is not None and value_node.text is not None:
            value = value_node.text
            if cell.attrib.get("t") == "s":
                value = shared_strings[int(value)]
        values.append(value)
    return values


def iter_rows(path: Path) -> Iterator[dict[str, str]]:
    suffix = path.suffix.lower()
    if suffix == ".csv":
        yield from iter_csv_rows(path)
        return
    if suffix == ".xlsx":
        yield from read_xlsx_rows(path)
        return
    raise ValueError(f"Unsupported input format: {path.suffix}")


def build_target_publishers(rows: Iterator[dict[str, str]]) -> dict[str, dict[str, object]]:
    target_publishers: dict[str, dict[str, object]] = {}

    for row in rows:
        publisher_name = normalize_text(row.get(EXPECTED_PUBLISHER_FIELD))
        if not publisher_name:
            continue

        publisher_bucket = target_publishers.setdefault(
            publisher_name,
            {"ios_ids": [], "google_play_ids": [], "top": None},
        )

        rank = parse_rank(row.get(EXPECTED_RANK_FIELD))
        current_rank = publisher_bucket.get("top")
        if rank is not None and (current_rank is None or rank < current_rank):
            publisher_bucket["top"] = rank

        for store_id in split_store_publisher_ids(row.get(EXPECTED_STORE_ID_FIELD)):
            bucket_name = classify_store_id(store_id)
            if not bucket_name:
                continue
            publisher_bucket[bucket_name].append(store_id)

    for buckets in target_publishers.values():
        buckets["ios_ids"] = dedupe_preserve_order(buckets["ios_ids"])
        buckets["google_play_ids"] = dedupe_preserve_order(buckets["google_play_ids"])

    return target_publishers


def save_target_publishers(data: dict[str, dict[str, object]], output_path: Path) -> None:
    output_path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def main(argv: list[str]) -> int:
    input_path = Path(argv[1]) if len(argv) > 1 else Path(r"C:\Users\aaa85\Desktop\畅销榜100.xlsx")
    output_path = Path(argv[2]) if len(argv) > 2 else Path("target_publishers.json")

    if not input_path.exists():
        print(f"[Error] Input file not found: {input_path}")
        return 1

    try:
        rows = iter_rows(input_path)
        target_publishers = build_target_publishers(rows)
        save_target_publishers(target_publishers, output_path)
    except Exception as exc:
        print(f"[Error] Failed to build target publishers JSON: {exc}")
        return 1

    print(f"[OK] Saved {len(target_publishers)} publishers to {output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
