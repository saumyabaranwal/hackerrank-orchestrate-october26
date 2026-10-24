"""File-format translators.

Each function takes one evidence file and returns Observation dicts.
The rest of the agent never cares whether the original was SQL, JSON, or a log.
"""

from __future__ import annotations

import json
import re
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

from .identity import HASH_RE, USER_RE, normalize_email, normalize_hash, normalize_phone

ISO_RE = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z")
RESOURCE_RE = re.compile(
    r"\b(?:account|search|analytics|support|export|backup|data_flow|"
    r"audit_record|tombstone|email_delivery|cache|legal|object|marketing)_[0-9A-Za-z]+\b"
)
KV_RE = re.compile(r'([A-Za-z_][A-Za-z0-9_]*)=("(?:[^"\\]|\\.)*"|[^\s]+)')

SERVICE_ALIASES = {
    "support_replica": "support_platform",
    "attachment_preview": "support_platform",
    "readback_collector": "account_service",
    "log_router": "account_service",
}

PREFIX_SYSTEM = {
    "account": "account_service",
    "search": "search_service",
    "analytics": "analytics_platform",
    "support": "support_platform",
    "export": "export_service",
    "backup": "backup_service",
    "data_flow": "integration_service",
    "audit_record": "security_service",
    "tombstone": "identity_service",
    "email_delivery": "email_delivery_service",
    "cache": "cache_service",
    "legal": "legal_service",
    "object": "object_storage",
    "marketing": "marketing_platform",
}
PREFIX_CATEGORY = {
    "account": "USER_PROFILE",
    "search": "SEARCH_INDEX_ENTRY",
    "analytics": "ANALYTICS_PROFILE",
    "support": "SUPPORT_MESSAGE",
    "export": "USER_EXPORT",
    "backup": "BACKUP_ARCHIVE",
    "data_flow": "DATA_FLOW",
    "audit_record": "SECURITY_AUDIT_LOG",
    "tombstone": "ACCOUNT_TOMBSTONE",
    "email_delivery": "EMAIL_DELIVERY_LOG",
    "cache": "CACHE_ENTRY",
    "legal": "LEGAL_HOLD_RECORD",
    "object": "SUPPORT_ATTACHMENT",
    "marketing": "MARKETING_PROFILE",
}
COLLECTION_CATEGORY = {
    "customer_profiles": "USER_PROFILE",
    "customer_search_documents": "SEARCH_INDEX_ENTRY",
    "customer_analytics_reports": "ANALYTICS_PROFILE",
    "customer_analytics_profiles": "ANALYTICS_PROFILE",
    "support_conversations": "SUPPORT_MESSAGE",
    "support_records": "SUPPORT_MESSAGE",
    "customer_export_jobs": "USER_EXPORT",
    "customer_exports": "USER_EXPORT",
    "connector_configurations": "DATA_FLOW",
    "connector_subscriptions": "DATA_FLOW",
    "backup_catalog": "BACKUP_ARCHIVE",
    "backup_restore_entries": "BACKUP_ARCHIVE",
    "security_audit_events": "SECURITY_AUDIT_LOG",
    "security_audit_records": "SECURITY_AUDIT_LOG",
    "deleted_customer_references": "ACCOUNT_TOMBSTONE",
}


def parse_ts(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    text = str(value).strip()
    for fmt in ("%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%dT%H:%M:%S.%fZ"):
        try:
            return datetime.strptime(text, fmt)
        except ValueError:
            continue
    match = ISO_RE.search(text)
    if match:
        try:
            return datetime.strptime(match.group(0), "%Y-%m-%dT%H:%M:%SZ")
        except ValueError:
            return None
    return None


def resource_prefix(resource_id: str) -> str:
    if resource_id.startswith("audit_record_"):
        return "audit_record"
    if resource_id.startswith("data_flow_"):
        return "data_flow"
    return resource_id.split("_", 1)[0]


def system_for(resource_id: str, fallback: str | None = None) -> str:
    raw = PREFIX_SYSTEM.get(resource_prefix(resource_id), fallback or resource_prefix(resource_id))
    return SERVICE_ALIASES.get(raw, raw)


def category_for(resource_id: str, record_type: str | None = None, collection: str | None = None) -> str:
    if record_type and record_type in PREFIX_CATEGORY.values():
        return record_type
    if collection and collection in COLLECTION_CATEGORY:
        return COLLECTION_CATEGORY[collection]
    return PREFIX_CATEGORY.get(resource_prefix(resource_id), "USER_PROFILE")


def truthy(value: Any) -> Optional[bool]:
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    text = str(value).strip().lower()
    if text in {"true", "1", "yes", "enabled", "active", "hit", "found", "present"}:
        return True
    if text in {"false", "0", "no", "disabled", "inactive", "miss", "not_found", "absent", "stopped", "null"}:
        return False
    return None


def pii_from_mapping(obj: Any) -> bool:
    if not isinstance(obj, dict):
        return False
    for key in (
        "email",
        "owner_email",
        "requester_email",
        "customer_email",
        "full_name",
        "name",
        "display_name",
        "requester_name",
        "phone",
        "requester_phone",
        "email_hash",
    ):
        value = obj.get(key)
        if value is None:
            continue
        if str(value).strip().lower() in {"", "null", "none"}:
            continue
        return True
    return False


def collect_ids(obj: Any) -> tuple[set[str], set[str], set[str], set[str]]:
    emails: set[str] = set()
    users: set[str] = set()
    phones: set[str] = set()
    hashes: set[str] = set()

    def walk(node: Any) -> None:
        if node is None:
            return
        if isinstance(node, dict):
            for key, value in node.items():
                if value is None or value == "":
                    continue
                text = str(value)
                lowered = key.lower()
                if "email_hash" in lowered or key in {"correlation_key"}:
                    digest = normalize_hash(text)
                    if digest:
                        hashes.add(digest)
                if "email" in lowered or key in {
                    "lookup_key",
                    "match_key",
                    "subject_key",
                    "owner_key",
                    "subject_selector",
                    "subject_reference",
                }:
                    email = normalize_email(text)
                    if email:
                        emails.add(email)
                if key in {
                    "user_id",
                    "customer_reference",
                    "subject_reference",
                    "subject_ref",
                    "lookup_key",
                    "correlation_key",
                    "subject_selector",
                }:
                    match = USER_RE.search(text)
                    if match:
                        users.add(match.group(0).lower())
                if "phone" in lowered:
                    phone = normalize_phone(text)
                    if phone:
                        phones.add(phone)
                walk(value)
            return
        if isinstance(node, (list, tuple)):
            for item in node:
                walk(item)
            return
        if isinstance(node, str):
            email = normalize_email(node)
            if email:
                emails.add(email)
            match = USER_RE.search(node)
            if match:
                users.add(match.group(0).lower())
            digest = normalize_hash(node)
            if digest:
                hashes.add(digest)

    walk(obj)
    return emails, users, phones, hashes


def observation(
    file_id: str,
    captured_at: Optional[datetime],
    system_id: str,
    resource_id: str,
    category: str,
    ident_obj: Any = None,
    observed_at: Optional[datetime] = None,
    present: Optional[bool] = None,
    pii_exposed: Optional[bool] = None,
    enabled: Optional[bool] = None,
    restore_allowed: Optional[bool] = None,
    replica_role: str = "unknown",
) -> dict[str, Any]:
    emails, users, phones, hashes = collect_ids(ident_obj)
    return {
        "file_id": file_id,
        "captured_at": captured_at,
        "observed_at": observed_at or captured_at,
        "system_id": system_id,
        "resource_id": resource_id,
        "category": category,
        "emails": emails,
        "user_ids": users,
        "phones": phones,
        "hashes": hashes,
        "present": present,
        "pii_exposed": pii_exposed,
        "enabled": enabled,
        "restore_allowed": restore_allowed,
        "replica_role": replica_role,
    }


def parse_lookup_record(file_id, captured_at, rec, default_observed=None) -> Optional[dict]:
    resource_id = rec.get("resource_id")
    if not resource_id:
        return None
    system_id = rec.get("system") or rec.get("system_id") or system_for(resource_id)
    record_type = rec.get("record_type")
    result = str(rec.get("result") or rec.get("status") or "").upper()
    observed = parse_ts(rec.get("recorded_at") or rec.get("observed_at")) or default_observed or captured_at
    category = category_for(resource_id, record_type)
    present = pii = enabled = restore = None
    if result in {"FOUND", "PRESENT", "HIT", "IDENTIFIABLE"}:
        present = True
        pii = result == "IDENTIFIABLE" or True
    elif result in {"NOT_FOUND", "ABSENT", "MISS", "MISSING"}:
        present = False
        pii = False
    elif result == "ANONYMIZED":
        present, pii = True, False
    elif result == "REDACTED":
        present, pii = True, False
    elif result == "ACTIVE":
        present = True
        if category == "DATA_FLOW":
            enabled = True
        elif category == "BACKUP_ARCHIVE":
            restore = True
    elif result == "DISABLED":
        present, enabled = True, False
    elif result == "BLOCKED":
        present, restore = True, False
    return observation(
        file_id,
        captured_at,
        system_id,
        resource_id,
        category,
        ident_obj=rec,
        observed_at=observed,
        present=present,
        pii_exposed=pii,
        enabled=enabled,
        restore_allowed=restore,
    )


def parse_sql_file(path: Path, file_id: str, captured_at: Optional[datetime]) -> list[dict]:
    text = path.read_text(encoding="utf-8")
    cap = captured_at
    match = re.search(r"Captured at:\s*(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z)", text)
    if match:
        cap = parse_ts(match.group(1)) or cap
    match = re.search(r"snapshot_completed_at=(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z)", text)
    if match:
        cap = parse_ts(match.group(1)) or cap
    sql = re.sub(r"CHECK\s*\(\s*json_valid\([^)]+\)\s*\)", "", text, flags=re.I)
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    try:
        conn.executescript(sql)
    except sqlite3.Error:
        conn.close()
        return []
    out: list[dict] = []
    tables = [row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")]
    for table in tables:
        if table == "snapshot_scope":
            continue
        role = "unknown"
        lowered = table.lower()
        if "primary" in lowered:
            role = "primary"
        elif "replica" in lowered or "failover" in lowered:
            role = "replica"
        rows = [dict(r) for r in conn.execute(f'SELECT * FROM "{table}"')]
        for row in rows:
            if "record_json" in row and row.get("resource_id"):
                try:
                    payload = json.loads(row["record_json"]) if isinstance(row["record_json"], str) else {}
                except json.JSONDecodeError:
                    payload = {}
                rid = row["resource_id"]
                origin = row.get("origin_system") or system_for(rid)
                collection = row.get("collection_name") or ""
                cat = category_for(rid, collection=collection)
                pii = pii_from_mapping(payload)
                if isinstance(payload, dict) and isinstance(payload.get("document"), dict):
                    pii = pii or pii_from_mapping(payload["document"])
                enabled = restore = None
                if isinstance(payload, dict):
                    if "enabled" in payload:
                        enabled = truthy(payload.get("enabled"))
                    if "restore_allowed" in payload:
                        restore = truthy(payload.get("restore_allowed"))
                    if cat == "ANALYTICS_PROFILE":
                        pii = bool(payload.get("user_id") or payload.get("email") or payload.get("phone") or payload.get("email_hash"))
                    if cat == "ACCOUNT_TOMBSTONE":
                        pii = bool(payload.get("name") or payload.get("email") or payload.get("phone") or payload.get("email_hash"))
                    if cat == "SUPPORT_MESSAGE":
                        msg = str(payload.get("message_text") or "")
                        pii = pii_from_mapping(payload) or ("@" in msg and "[REDACTED]" not in msg)
                out.append(
                    observation(
                        file_id, cap, origin, rid, cat, ident_obj=payload if payload else row,
                        observed_at=parse_ts(row.get("updated_at")) or cap, present=True,
                        pii_exposed=pii, enabled=enabled, restore_allowed=restore, replica_role=role,
                    )
                )
                continue
            rid = row.get("resource_id")
            if not rid:
                continue
            cat, sys_id, enabled, restore, pii = _inventory_shape(table, rid, row)
            out.append(
                observation(
                    file_id, cap, sys_id, rid, cat, ident_obj=row,
                    observed_at=parse_ts(row.get("updated_at")) or cap, present=True,
                    pii_exposed=pii, enabled=enabled, restore_allowed=restore, replica_role=role,
                )
            )
    conn.close()
    return out


def _inventory_shape(table: str, rid: str, row: dict) -> tuple[str, str, Optional[bool], Optional[bool], bool]:
    name = table.lower()
    mapping = {
        "customer_profiles": ("USER_PROFILE", "account_service"),
        "customer_search_documents": ("SEARCH_INDEX_ENTRY", "search_service"),
        "customer_analytics_profiles": ("ANALYTICS_PROFILE", "analytics_platform"),
        "support_records": ("SUPPORT_MESSAGE", "support_platform"),
        "customer_exports": ("USER_EXPORT", "export_service"),
        "connector_subscriptions": ("DATA_FLOW", "integration_service"),
        "backup_restore_entries": ("BACKUP_ARCHIVE", "backup_service"),
        "security_audit_records": ("SECURITY_AUDIT_LOG", "security_service"),
    }
    cat, sys_id = mapping.get(name, (category_for(rid), system_for(rid)))
    enabled = truthy(row.get("enabled")) if cat == "DATA_FLOW" else None
    restore = truthy(row.get("restore_allowed")) if cat == "BACKUP_ARCHIVE" else None
    if cat == "ANALYTICS_PROFILE":
        pii = bool(row.get("email") or row.get("customer_reference") or row.get("email_hash") or row.get("phone"))
    else:
        pii = pii_from_mapping(row)
    return cat, sys_id, enabled, restore, pii


def parse_snapshot_bundle(path: Path, file_id: str, captured_at: Optional[datetime]) -> list[dict]:
    data = json.loads(path.read_text(encoding="utf-8"))
    exported = parse_ts(data.get("exported_at")) or captured_at
    out: list[dict] = []
    for snap in data.get("snapshots") or []:
        store = snap.get("data_store") or ""
        collection = snap.get("collection") or ""
        cap = parse_ts(snap.get("captured_at")) or exported
        for rec in snap.get("records") or []:
            rid = rec.get("resource_id")
            if not rid:
                continue
            cat = category_for(rid, collection=collection)
            ident = dict(rec)
            if isinstance(rec.get("document"), dict):
                ident.update(rec["document"])
            pii = pii_from_mapping(ident)
            enabled = truthy(rec.get("enabled")) if cat == "DATA_FLOW" else None
            restore = truthy(rec.get("restore_allowed")) if cat == "BACKUP_ARCHIVE" else None
            if cat == "ANALYTICS_PROFILE":
                pii = bool(rec.get("user_id") or rec.get("email") or rec.get("phone") or rec.get("email_hash"))
            if cat == "ACCOUNT_TOMBSTONE":
                pii = bool(rec.get("name") or rec.get("email") or rec.get("phone") or rec.get("email_hash"))
            out.append(
                observation(
                    file_id, cap, store or system_for(rid), rid, cat, ident_obj=ident,
                    observed_at=cap, present=True, pii_exposed=pii, enabled=enabled, restore_allowed=restore,
                )
            )
    return out


def parse_service_export(path: Path, file_id: str, captured_at: Optional[datetime]) -> list[dict]:
    data = json.loads(path.read_text(encoding="utf-8"))
    exported = parse_ts(data.get("exported_at")) or captured_at
    exports = data.get("service_exports") or {}
    out: list[dict] = []

    for rec in (exports.get("account_service") or {}).get("profile_lookups") or []:
        rid = rec.get("resource_id")
        if not rid:
            continue
        profile = rec.get("profile")
        present = rec.get("status_code") == 200 and profile is not None
        ident = dict(rec)
        if isinstance(profile, dict):
            ident.update(profile)
        out.append(
            observation(
                file_id, exported, "account_service", rid, "USER_PROFILE", ident_obj=ident,
                observed_at=parse_ts(rec.get("observed_at")) or exported,
                present=present, pii_exposed=pii_from_mapping(profile) if isinstance(profile, dict) else False,
            )
        )

    for rec in (exports.get("analytics_platform") or {}).get("profiles") or []:
        rid = rec.get("resource_id")
        if not rid:
            continue
        pii = bool(rec.get("email") or rec.get("customer_reference") or rec.get("email_hash") or rec.get("phone"))
        out.append(
            observation(
                file_id, exported, "analytics_platform", rid, "ANALYTICS_PROFILE", ident_obj=rec,
                observed_at=parse_ts(rec.get("observed_at")) or exported, present=True, pii_exposed=pii,
            )
        )

    for rec in (exports.get("backup_service") or {}).get("restore_entries") or []:
        rid = rec.get("resource_id")
        if not rid:
            continue
        out.append(
            observation(
                file_id, exported, "backup_service", rid, "BACKUP_ARCHIVE", ident_obj=rec,
                observed_at=parse_ts(rec.get("observed_at")) or exported, present=True, pii_exposed=False,
                restore_allowed=truthy(rec.get("restore_allowed")),
            )
        )

    for rec in (exports.get("export_service") or {}).get("exports") or []:
        rid = rec.get("resource_id")
        if not rid:
            continue
        out.append(
            observation(
                file_id, exported, "export_service", rid, "USER_EXPORT", ident_obj=rec,
                observed_at=parse_ts(rec.get("observed_at")) or exported, present=True, pii_exposed=pii_from_mapping(rec),
            )
        )

    for rec in (exports.get("integration_service") or {}).get("connectors") or []:
        rid = rec.get("resource_id")
        if not rid:
            continue
        out.append(
            observation(
                file_id, exported, "integration_service", rid, "DATA_FLOW", ident_obj=rec,
                observed_at=parse_ts(rec.get("observed_at")) or exported, present=True, pii_exposed=False,
                enabled=truthy(rec.get("enabled")),
            )
        )

    for rec in (exports.get("search_service") or {}).get("index_queries") or []:
        rid = rec.get("resource_id")
        hits = rec.get("hits") or {}
        docs = hits.get("documents") if isinstance(hits, dict) else None
        total = hits.get("total") if isinstance(hits, dict) else 0
        present = bool(docs) or (isinstance(total, int) and total > 0)
        ident = dict(rec)
        pii = False
        if docs:
            for doc in docs:
                ident.update(doc)
                pii = pii or pii_from_mapping(doc)
                rid = doc.get("resource_id") or rid
        obs = observation(
            file_id, exported, "search_service", rid, "SEARCH_INDEX_ENTRY", ident_obj=ident,
            observed_at=parse_ts(rec.get("observed_at")) or exported, present=present, pii_exposed=pii,
        )
        query = rec.get("query")
        if query:
            email = normalize_email(str(query))
            if email:
                obs["emails"].add(email)
        out.append(obs)

    for rec in (exports.get("security_service") or {}).get("audit_records") or []:
        rid = rec.get("resource_id")
        if not rid:
            continue
        out.append(
            observation(
                file_id, exported, "security_service", rid, "SECURITY_AUDIT_LOG", ident_obj=rec,
                observed_at=parse_ts(rec.get("observed_at")) or exported, present=True, pii_exposed=False,
            )
        )

    for rec in (exports.get("support_platform") or {}).get("tickets") or []:
        rid = rec.get("resource_id")
        if not rid:
            continue
        out.append(
            observation(
                file_id, exported, "support_platform", rid, "SUPPORT_MESSAGE", ident_obj=rec,
                observed_at=parse_ts(rec.get("observed_at")) or exported, present=True, pii_exposed=pii_from_mapping(rec),
            )
        )
    return out


def parse_generic_json(path: Path, file_id: str, captured_at: Optional[datetime]) -> list[dict]:
    data = json.loads(path.read_text(encoding="utf-8"))
    exported = parse_ts(data.get("exported_at") or data.get("captured_at")) or captured_at
    records = data.get("records")
    out: list[dict] = []
    if isinstance(records, list) and records and isinstance(records[0], dict) and "resource_id" in records[0]:
        # lookup-style OR export-jobs / analytics report
        for rec in records:
            if "record_type" in rec or "result" in rec:
                parsed = parse_lookup_record(file_id, exported, rec, exported)
                if parsed:
                    out.append(parsed)
                continue
            rid = rec.get("resource_id")
            if not rid:
                continue
            cat = category_for(rid, collection=data.get("collection"))
            pii = pii_from_mapping(rec)
            if cat == "ANALYTICS_PROFILE":
                pii = bool(rec.get("user_id") or rec.get("email") or rec.get("phone") or rec.get("email_hash"))
            out.append(
                observation(
                    file_id, exported, system_for(rid), rid, cat, ident_obj=rec,
                    observed_at=exported, present=True, pii_exposed=pii,
                )
            )
    return out


def parse_handover_txt(path: Path, file_id: str, captured_at: Optional[datetime]) -> list[dict]:
    text = path.read_text(encoding="utf-8")
    cap = captured_at
    match = re.search(r"Snapshot:\s*(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z)", text)
    if match:
        cap = parse_ts(match.group(1)) or cap
    line_re = re.compile(
        r"^-\s+(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z)\s*\|\s*([^|]+)\|\s*([^|]+)\|\s*([^|]+)\|\s*([^|]+)\|\s*(.*)$"
    )
    out: list[dict] = []
    for line in text.splitlines():
        found = line_re.match(line.strip())
        if not found:
            continue
        ts, system, rid, rtype, result, subject = [part.strip() for part in found.groups()]
        rec = {
            "recorded_at": ts,
            "system": system,
            "resource_id": rid,
            "record_type": rtype,
            "result": result,
            "subject_reference": None if subject in {"no direct identifier", ""} else subject,
            "lookup_key": subject,
        }
        parsed = parse_lookup_record(file_id, cap, rec, parse_ts(ts))
        if parsed:
            out.append(parsed)
    return out


def parse_kv_line(line: str) -> dict[str, str]:
    data: dict[str, str] = {}
    match = ISO_RE.search(line)
    if match:
        data["timestamp"] = match.group(0)
    brace = line.find("{")
    if brace != -1:
        try:
            obj = json.loads(line[brace:])
            if isinstance(obj, dict):
                for key, value in obj.items():
                    if value is not None:
                        data[str(key)] = str(value)
                return data
        except json.JSONDecodeError:
            pass
    for key, value in KV_RE.findall(line):
        if value.startswith('"') and value.endswith('"'):
            value = value[1:-1]
        data[key] = value
    if "|" in line and "service" not in data:
        parts = [part.strip() for part in line.split("|")]
        if len(parts) >= 5 and ISO_RE.search(parts[0] or ""):
            data.setdefault("timestamp", ISO_RE.search(parts[0]).group(0))
            data.setdefault("service", parts[2])
            data.setdefault("trace_id", parts[3])
            data.setdefault("event", parts[4].split()[0] if parts[4] else "")
            rest = "|".join(parts[5:]) if len(parts) > 5 else ""
            for key, value in KV_RE.findall(rest):
                if value.startswith('"') and value.endswith('"'):
                    value = value[1:-1]
                data[key] = value
    return data


def parse_logs(path: Path, file_id: str, captured_at: Optional[datetime]) -> list[dict]:
    parsed = [parse_kv_line(line) for line in path.read_text(encoding="utf-8", errors="replace").splitlines() if line.strip()]
    by_trace: dict[str, list[dict[str, str]]] = {}
    ungrouped: list[dict[str, str]] = []
    for item in parsed:
        trace = item.get("trace_id") or item.get("trace") or ""
        if trace:
            by_trace.setdefault(trace, []).append(item)
        else:
            ungrouped.append(item)

    out: list[dict] = []

    def emit(group: list[dict[str, str]]) -> None:
        merged: dict[str, str] = {}
        for item in group:
            for key in (
                "lookup_key", "match_key", "subject_key", "subject_ref",
                "correlation_key", "owner_key", "customer_email",
                "customer_reference", "subject_reference", "email", "requester_email",
            ):
                if item.get(key):
                    merged[key] = item[key]
        for item in group:
            rid = item.get("resource_id")
            if not rid or not RESOURCE_RE.search(rid):
                continue
            event = (item.get("event") or "").lower()
            service = SERVICE_ALIASES.get(item.get("service") or "", item.get("service")) or system_for(rid)
            ts = parse_ts(item.get("timestamp")) or captured_at
            cat = category_for(rid)
            present = pii = enabled = restore = None
            rows, http_status, result = item.get("rows"), item.get("http_status") or item.get("status_code"), (item.get("result") or "").lower()
            if "completed" in event or event in {"message_read", "connector_config_loaded", "contact_query_completed"}:
                if http_status:
                    present = str(http_status) == "200"
                elif rows is not None:
                    try:
                        present = int(rows) > 0
                    except ValueError:
                        present = rows not in {"0", "false"}
                elif result in {"hit", "found"}:
                    present = True
                elif result in {"miss", "not_found"}:
                    present = False
                else:
                    present = True
            if event == "connector_heartbeat":
                enabled, present, cat = truthy(item.get("enabled")), True, "DATA_FLOW"
            if event == "restore_candidate_evaluated":
                restore, present, cat = (truthy(item.get("eligible")) and not truthy(item.get("deletion_block"))), True, "BACKUP_ARCHIVE"
            if "restore_policy" in event and item.get("restore_allowed") is not None:
                restore, present, cat = truthy(item.get("restore_allowed")), True, "BACKUP_ARCHIVE"
            if event in {"connector_config_read_completed", "connector_config_loaded"}:
                enabled, present, cat = truthy(item.get("enabled")), True, "DATA_FLOW"
            if event == "export_download_check_completed":
                present, cat = (truthy(item.get("available")) if item.get("available") is not None else True), "USER_EXPORT"
            if event == "index_query_completed":
                present, cat = (result != "miss"), "SEARCH_INDEX_ENTRY"
            if event in {"message_pii_scan", "attachment_pii_scan", "analytics_identity_scan"}:
                present, pii = True, True
            if event in {"contact_query_completed", "contact_lookup_completed"}:
                try:
                    present = int(item.get("rows") or "1") > 0
                except ValueError:
                    present = True
                pii = True
                if event == "contact_query_completed":
                    cat = "SUPPORT_ATTACHMENT"
                elif item.get("email_opt_in"):
                    cat = "SECONDARY_IDENTIFIER"
            if event == "analytics_profile_read_completed":
                pii = bool(item.get("email") and item.get("email") not in {"null", "None", ""})
                present, cat = True, "ANALYTICS_PROFILE"
            if event in {"support_ticket_read_completed", "message_read"}:
                present, cat = True, "SUPPORT_MESSAGE"
                pii = bool(item.get("requester_email") and item.get("requester_email") not in {"null", ""})
                if item.get("message_text") == "[REDACTED]":
                    pii = False
            if event == "audit_record_read_completed":
                present, pii, cat = True, False, "SECURITY_AUDIT_LOG"
            ident = dict(item)
            ident.update(merged)
            out.append(
                observation(
                    file_id, captured_at, service, rid, cat, ident_obj=ident, observed_at=ts,
                    present=present, pii_exposed=pii, enabled=enabled, restore_allowed=restore,
                )
            )
            if item.get("event") == "record_lookup" and item.get("resource_id"):
                parsed = parse_lookup_record(
                    file_id,
                    captured_at,
                    {
                        "resource_id": item["resource_id"],
                        "system": item.get("system") or item.get("service"),
                        "record_type": item.get("record_type"),
                        "result": item.get("result"),
                        "subject_reference": item.get("subject_reference"),
                        "recorded_at": item.get("timestamp"),
                    },
                    parse_ts(item.get("timestamp")),
                )
                if parsed:
                    out.append(parsed)

    for group in by_trace.values():
        emit(group)
    emit(ungrouped)
    return out


def parse_pdf(path: Path, file_id: str, captured_at: Optional[datetime]) -> list[dict]:
    try:
        from pypdf import PdfReader
    except ImportError:
        return []
    try:
        reader = PdfReader(str(path))
        text = "\n".join((page.extract_text() or "") for page in reader.pages)
    except Exception:
        return []
    out: list[dict] = []
    emails = set()
    for match in re.findall(r"[A-Z0-9._%+\-]+@[A-Z0-9.\-]+\.[A-Z]{2,}", text, flags=re.I):
        email = normalize_email(match)
        if email:
            emails.add(email)
    users = {m.lower() for m in USER_RE.findall(text)}
    support = re.search(r"(support_\d+)", text)
    if support:
        obs = observation(
            file_id, captured_at, "support_platform", support.group(1), "SUPPORT_ATTACHMENT",
            ident_obj={"email": next(iter(emails), None), "user_id": next(iter(users), None)},
            present=True, pii_exposed=True,
        )
        obs["emails"] |= emails
        obs["user_ids"] |= users
        out.append(obs)
    audit = re.search(r"(audit_record_[0-9A-Za-z]+)", text)
    if audit and ("Event reference" in text or "audit_record_" in text):
        obs = observation(
            file_id, captured_at, "security_service", audit.group(1), "SECURITY_AUDIT_LOG",
            present=True, pii_exposed=False,
        )
        obs["user_ids"] |= users
        out.append(obs)
    return out


def parse_evidence_file(path: Path, file_id: str, captured_at: Optional[datetime]) -> list[dict]:
    suffix = path.suffix.lower()
    name = path.name.lower()
    if not path.exists():
        return []
    try:
        if suffix == ".sql":
            return parse_sql_file(path, file_id, captured_at)
        if suffix == ".json":
            if "snapshot_bundle" in name:
                return parse_snapshot_bundle(path, file_id, captured_at)
            if "service_resource_export" in name:
                return parse_service_export(path, file_id, captured_at)
            return parse_generic_json(path, file_id, captured_at)
        if suffix == ".txt":
            return parse_handover_txt(path, file_id, captured_at)
        if suffix == ".log":
            return parse_logs(path, file_id, captured_at)
        if suffix == ".pdf":
            return parse_pdf(path, file_id, captured_at)
    except Exception:
        return []
    return []
