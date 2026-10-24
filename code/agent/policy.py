"""Brain 4 — the company rulebook.

deletion_rules.csv says what MUST happen to each kind of record.
The agent is not allowed to invent extra treatments.
"""

from __future__ import annotations

import csv
from pathlib import Path

# Operations the grader accepts, in the required sort order inside each phase.
FINDING_OPS = [
    "REPORT_REMAINING_RECORD",
    "REPORT_EXPOSED_PII",
    "REPORT_ACTIVE_DATA_FLOW",
    "REPORT_RESTORE_RISK",
]
REMEDIATION_OPS = [
    "DISABLE_DATA_FLOW",
    "BLOCK_RESTORE",
    "DELETE_RECORD",
    "REDACT_RECORD",
    "ANONYMIZE_RECORD",
]
VERIFICATION_OPS = [
    "VERIFY_RECORD_ABSENT",
    "VERIFY_RECORD_PRESENT",
    "VERIFY_RECORD_REDACTED",
    "VERIFY_RECORD_ANONYMIZED",
    "VERIFY_DATA_FLOW_DISABLED",
    "VERIFY_RESTORE_BLOCKED",
]

OP_STATE = {
    "REPORT_REMAINING_RECORD": "PRESENT",
    "REPORT_EXPOSED_PII": "PRESENT",
    "REPORT_ACTIVE_DATA_FLOW": "ACTIVE",
    "REPORT_RESTORE_RISK": "ACTIVE",
    "DISABLE_DATA_FLOW": "DISABLED",
    "BLOCK_RESTORE": "BLOCKED",
    "DELETE_RECORD": "ABSENT",
    "REDACT_RECORD": "REDACTED",
    "ANONYMIZE_RECORD": "ANONYMIZED",
    "VERIFY_RECORD_ABSENT": "ABSENT",
    "VERIFY_RECORD_PRESENT": "PRESENT",
    "VERIFY_RECORD_REDACTED": "REDACTED",
    "VERIFY_RECORD_ANONYMIZED": "ANONYMIZED",
    "VERIFY_DATA_FLOW_DISABLED": "DISABLED",
    "VERIFY_RESTORE_BLOCKED": "BLOCKED",
}

DELETE_CATEGORIES = {
    "USER_PROFILE",
    "SECONDARY_IDENTIFIER",
    "SEARCH_INDEX_ENTRY",
    "CACHE_ENTRY",
    "SUPPORT_ATTACHMENT",
    "USER_EXPORT",
    "MARKETING_PROFILE",
}
REDACT_CATEGORIES = {
    "SUPPORT_MESSAGE",
    "EMAIL_DELIVERY_LOG",
    "ACCOUNT_TOMBSTONE",
}
ANONYMIZE_CATEGORIES = {
    "ANALYTICS_PROFILE",
    "PRODUCT_TELEMETRY",
}
RETAIN_CATEGORIES = {
    "SECURITY_AUDIT_LOG",
    "LEGAL_HOLD_RECORD",
    "BACKUP_ARCHIVE",
}


def load_rules(dataset_dir: Path) -> dict[str, str]:
    """category -> DELETE | REDACT | ANONYMIZE | RETAIN from the CSV."""
    path = dataset_dir / "deletion_rules.csv"
    mapping: dict[str, str] = {}
    with path.open(newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            mapping[row["data_category"]] = row["required_action"]
    return mapping


def required_action(category: str, rules: dict[str, str] | None = None) -> str:
    if category == "DATA_FLOW":
        return "DISABLE"
    if rules and category in rules:
        return rules[category]
    if category in DELETE_CATEGORIES:
        return "DELETE"
    if category in REDACT_CATEGORIES:
        return "REDACT"
    if category in ANONYMIZE_CATEGORIES:
        return "ANONYMIZE"
    if category in RETAIN_CATEGORIES:
        return "RETAIN"
    return "DELETE"
