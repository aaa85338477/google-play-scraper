from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import requests
import streamlit as st


FEISHU_BASE_URL = "https://open.feishu.cn/open-apis"
TENANT_ACCESS_TOKEN_URL = f"{FEISHU_BASE_URL}/auth/v3/tenant_access_token/internal"
BITABLE_RECORDS_URL_TEMPLATE = (
    f"{FEISHU_BASE_URL}/bitable/v1/apps/{{app_token}}/tables/{{table_id}}/records"
)
BATCH_CREATE_RECORDS_URL_TEMPLATE = (
    f"{FEISHU_BASE_URL}/bitable/v1/apps/{{app_token}}/tables/{{table_id}}/records/batch_create"
)
BITABLE_FIELDS_URL_TEMPLATE = (
    f"{FEISHU_BASE_URL}/bitable/v1/apps/{{app_token}}/tables/{{table_id}}/fields"
)
REQUEST_TIMEOUT = 30
DEFAULT_PAGE_SIZE = 500
RICH_FIELD_NAMES = [
    "App_ID",
    "Raw_App_ID",
    "Title",
    "Store",
    "Developer",
    "Store_URL",
    "Icon_URL",
    "Market_Signal",
    "Company_Region",
    "Company_Type",
    "Company_Scale",
    "Watch_Priority",
    "Release_Date",
    "Source",
    "First_Seen_At",
]


def get_feishu_config() -> dict[str, str]:
    return {
        "app_id": st.secrets["FEISHU_APP_ID"],
        "app_secret": st.secrets["FEISHU_APP_SECRET"],
        "app_token": st.secrets["FEISHU_APP_TOKEN"],
        "table_id": st.secrets["FEISHU_TABLE_ID"],
    }


def get_tenant_access_token() -> str | None:
    config = get_feishu_config()
    payload = {
        "app_id": config["app_id"],
        "app_secret": config["app_secret"],
    }

    try:
        response = requests.post(
            TENANT_ACCESS_TOKEN_URL,
            json=payload,
            timeout=REQUEST_TIMEOUT,
        )
        response.raise_for_status()
    except requests.RequestException as exc:
        print(f"[Feishu] Failed to get tenant_access_token: {exc}")
        return None

    result = response.json()
    if result.get("code") != 0:
        print(f"[Feishu] tenant_access_token error: {result}")
        return None

    return result.get("tenant_access_token")


def build_headers(tenant_access_token: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {tenant_access_token}",
        "Content-Type": "application/json; charset=utf-8",
    }


def list_bitable_records(tenant_access_token: str) -> list[dict[str, Any]]:
    config = get_feishu_config()
    url = BITABLE_RECORDS_URL_TEMPLATE.format(
        app_token=config["app_token"],
        table_id=config["table_id"],
    )
    headers = build_headers(tenant_access_token)

    all_items: list[dict[str, Any]] = []
    page_token: str | None = None

    while True:
        params: dict[str, Any] = {"page_size": DEFAULT_PAGE_SIZE}
        if page_token:
            params["page_token"] = page_token

        try:
            response = requests.get(
                url,
                headers=headers,
                params=params,
                timeout=REQUEST_TIMEOUT,
            )
            response.raise_for_status()
        except requests.RequestException as exc:
            print(f"[Feishu] Failed to list bitable records: {exc}")
            break

        result = response.json()
        if result.get("code") != 0:
            print(f"[Feishu] list records error: {result}")
            break

        data = result.get("data", {})
        items = data.get("items", [])
        all_items.extend(items)

        if not data.get("has_more"):
            break

        page_token = data.get("page_token")
        if not page_token:
            break

    return all_items


def list_bitable_fields(tenant_access_token: str) -> list[dict[str, Any]]:
    config = get_feishu_config()
    url = BITABLE_FIELDS_URL_TEMPLATE.format(
        app_token=config["app_token"],
        table_id=config["table_id"],
    )
    headers = build_headers(tenant_access_token)

    try:
        response = requests.get(url, headers=headers, timeout=REQUEST_TIMEOUT)
        response.raise_for_status()
    except requests.RequestException as exc:
        print(f"[Feishu] Failed to list bitable fields: {exc}")
        return []

    result = response.json()
    if result.get("code") != 0:
        print(f"[Feishu] list fields error: {result}")
        return []

    return result.get("data", {}).get("items", [])


def extract_field_names(fields: list[dict[str, Any]]) -> set[str]:
    return {str(field.get("field_name")).strip() for field in fields if field.get("field_name")}


def extract_app_ids(records: list[dict[str, Any]], field_name: str = "App_ID") -> list[str]:
    app_ids: list[str] = []

    for record in records:
        fields = record.get("fields", {})
        raw_value = fields.get(field_name)

        if isinstance(raw_value, str) and raw_value.strip():
            app_ids.append(raw_value.strip())
            continue

        if isinstance(raw_value, list):
            for item in raw_value:
                if isinstance(item, str) and item.strip():
                    app_ids.append(item.strip())

    return app_ids


def get_existing_app_ids() -> list[str]:
    tenant_access_token = get_tenant_access_token()
    if not tenant_access_token:
        return []

    records = list_bitable_records(tenant_access_token)
    return extract_app_ids(records)


def diff_new_app_ids(new_scraped_ids: list[str], existing_app_ids: list[str]) -> list[str]:
    existing_set = {app_id.strip() for app_id in existing_app_ids if app_id.strip()}
    deduped_new_ids: list[str] = []

    for app_id in new_scraped_ids:
        normalized = app_id.strip()
        if not normalized:
            continue
        if normalized in existing_set or normalized in deduped_new_ids:
            continue
        deduped_new_ids.append(normalized)

    return deduped_new_ids


def create_bitable_records(tenant_access_token: str, app_ids: list[str]) -> bool:
    if not app_ids:
        return True

    config = get_feishu_config()
    url = BATCH_CREATE_RECORDS_URL_TEMPLATE.format(
        app_token=config["app_token"],
        table_id=config["table_id"],
    )
    headers = build_headers(tenant_access_token)
    payload = {
        "records": [{"fields": {"App_ID": app_id}} for app_id in app_ids],
    }

    try:
        response = requests.post(
            url,
            headers=headers,
            json=payload,
            timeout=REQUEST_TIMEOUT,
        )
        response.raise_for_status()
    except requests.RequestException as exc:
        print(f"[Feishu] Failed to create bitable records: {exc}")
        return False

    result = response.json()
    if result.get("code") != 0:
        print(f"[Feishu] create records error: {result}")
        return False

    return True


def normalize_text(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def build_record_identifier(game: dict[str, Any]) -> str:
    explicit = normalize_text(game.get("feishu_app_id") or game.get("sync_app_id"))
    if explicit:
        return explicit

    raw_app_id = normalize_text(game.get("app_id"))
    store = normalize_text(game.get("store"))
    if raw_app_id and store:
        return f"{store}::{raw_app_id}"
    return raw_app_id


def build_game_record_fields(game: dict[str, Any]) -> dict[str, str]:
    record_id = build_record_identifier(game)
    raw_app_id = normalize_text(game.get("raw_app_id") or game.get("app_id"))
    developer = normalize_text(game.get("developer") or game.get("developer_name"))
    source = normalize_text(game.get("source") or game.get("developer_label"))
    fields = {
        "App_ID": record_id,
        "Raw_App_ID": raw_app_id,
        "Title": normalize_text(game.get("title")),
        "Store": normalize_text(game.get("store")),
        "Developer": developer,
        "Store_URL": normalize_text(game.get("url")),
        "Icon_URL": normalize_text(game.get("icon_url")),
        "Market_Signal": normalize_text(game.get("market_signal")),
        "Company_Region": normalize_text(game.get("company_region")),
        "Company_Type": normalize_text(game.get("company_type")),
        "Company_Scale": normalize_text(game.get("company_scale")),
        "Watch_Priority": normalize_text(game.get("watch_priority")),
        "Release_Date": normalize_text(game.get("released_at")),
        "Source": source,
        "First_Seen_At": datetime.now(timezone.utc).isoformat(),
    }
    return {key: value for key, value in fields.items() if value}


def filter_record_fields(fields: dict[str, str], available_field_names: set[str]) -> dict[str, str]:
    if not available_field_names:
        return {"App_ID": fields["App_ID"]}
    filtered = {key: value for key, value in fields.items() if key in available_field_names}
    if "App_ID" not in filtered and "App_ID" in fields:
        filtered["App_ID"] = fields["App_ID"]
    return filtered


def diff_new_game_records(game_records: list[dict[str, Any]], existing_app_ids: list[str]) -> list[dict[str, Any]]:
    existing_set = {normalize_text(app_id) for app_id in existing_app_ids if normalize_text(app_id)}
    deduped_records: list[dict[str, Any]] = []
    seen_ids: set[str] = set()

    for game in game_records:
        record_id = build_record_identifier(game)
        if not record_id or record_id in existing_set or record_id in seen_ids:
            continue
        seen_ids.add(record_id)
        deduped_records.append(game)

    return deduped_records


def create_bitable_game_records(
    tenant_access_token: str,
    game_records: list[dict[str, Any]],
    available_field_names: set[str],
) -> bool:
    if not game_records:
        return True

    config = get_feishu_config()
    url = BATCH_CREATE_RECORDS_URL_TEMPLATE.format(
        app_token=config["app_token"],
        table_id=config["table_id"],
    )
    headers = build_headers(tenant_access_token)
    payload = {
        "records": [
            {"fields": filter_record_fields(build_game_record_fields(game), available_field_names)}
            for game in game_records
        ],
    }

    try:
        response = requests.post(
            url,
            headers=headers,
            json=payload,
            timeout=REQUEST_TIMEOUT,
        )
        response.raise_for_status()
    except requests.RequestException as exc:
        print(f"[Feishu] Failed to create rich bitable records: {exc}")
        return False

    result = response.json()
    if result.get("code") != 0:
        print(f"[Feishu] create rich records error: {result}")
        return False

    return True


def sync_game_records_to_bitable(game_records: list[dict[str, Any]]) -> dict[str, Any]:
    tenant_access_token = get_tenant_access_token()
    if not tenant_access_token:
        return {
            "success": False,
            "existing_app_ids": [],
            "new_app_ids": [],
            "written_count": 0,
            "field_names": [],
        }

    existing_records = list_bitable_records(tenant_access_token)
    existing_app_ids = extract_app_ids(existing_records)
    fields = list_bitable_fields(tenant_access_token)
    field_names = extract_field_names(fields)
    new_game_records = diff_new_game_records(game_records, existing_app_ids)
    new_app_ids = [build_record_identifier(game) for game in new_game_records]

    write_success = create_bitable_game_records(
        tenant_access_token,
        new_game_records,
        field_names,
    )
    written_count = len(new_game_records) if write_success else 0

    return {
        "success": write_success,
        "existing_app_ids": existing_app_ids,
        "new_app_ids": new_app_ids,
        "written_count": written_count,
        "field_names": sorted(field_names),
        "used_rich_fields": len(field_names) > 1,
    }


def sync_new_app_ids_to_bitable(new_scraped_ids: list[str]) -> dict[str, Any]:
    tenant_access_token = get_tenant_access_token()
    if not tenant_access_token:
        return {
            "success": False,
            "existing_app_ids": [],
            "new_app_ids": [],
            "written_count": 0,
        }

    existing_app_ids = extract_app_ids(list_bitable_records(tenant_access_token))
    new_app_ids = diff_new_app_ids(new_scraped_ids, existing_app_ids)

    write_success = create_bitable_records(tenant_access_token, new_app_ids)
    written_count = len(new_app_ids) if write_success else 0

    return {
        "success": write_success,
        "existing_app_ids": existing_app_ids,
        "new_app_ids": new_app_ids,
        "written_count": written_count,
    }


if __name__ == "__main__":
    new_scraped_ids = ["id1", "id2", "id3"]
    result = sync_new_app_ids_to_bitable(new_scraped_ids)
    print(result)
