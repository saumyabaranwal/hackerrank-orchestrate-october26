"""Brain 5 — turn facts + rules into the official step list.

COMPLETE  -> only proof checks, each with an evidence_id
INCOMPLETE -> findings (cited) + fixes + later checks (empty evidence_id)
NOT_APPLICABLE -> []
"""

from __future__ import annotations

import csv
import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Optional

from .evidence import EvidenceStore, Observation
from .identity import ResolvedIdentity
from .parsers import parse_ts
from .policy import (
    FINDING_OPS,
    OP_STATE,
    REMEDIATION_OPS,
    VERIFICATION_OPS,
    load_rules,
    required_action,
)


@dataclass
class ResourceState:
    system_id: str
    resource_id: str
    category: str
    present: bool
    pii_exposed: bool
    enabled: Optional[bool]
    restore_allowed: Optional[bool]
    evidence_id: str


def _latest_states(hits: list[Observation]) -> dict[tuple[str, str], ResourceState]:
    grouped: dict[tuple[str, str], list[Observation]] = {}
    for obs in hits:
        grouped.setdefault((obs.system_id, obs.resource_id), []).append(obs)

    states: dict[tuple[str, str], ResourceState] = {}
    for key, items in grouped.items():
        latest_cap = max((item.captured_at or datetime.min for item in items), default=datetime.min)
        latest = [item for item in items if (item.captured_at or datetime.min) == latest_cap]
        presents = [item.present for item in latest if item.present is not None]
        present = any(presents) if presents else True
        pii = any(item.pii_exposed for item in latest if item.pii_exposed) if present else False
        enabled_vals = [item.enabled for item in latest if item.enabled is not None]
        restore_vals = [item.restore_allowed for item in latest if item.restore_allowed is not None]
        chosen = next((item for item in latest if item.present == present), latest[0])
        states[key] = ResourceState(
            system_id=key[0],
            resource_id=key[1],
            category=chosen.category,
            present=bool(present),
            pii_exposed=bool(pii),
            enabled=any(enabled_vals) if enabled_vals else None,
            restore_allowed=any(restore_vals) if restore_vals else None,
            evidence_id=chosen.file_id,
        )
    return states


def _maybe_account_from_activity(
    dataset_dir: Path,
    row: dict,
    states: dict[tuple[str, str], ResourceState],
    store: EvidenceStore,
) -> None:
    """If evidence never named the account row, a nearby deletion-worker
    event can still tell us the resource_id. Only used when nothing else
    linked an account, and only if it happened within 15 minutes of reported_at.
    """
    if any(st.category == "USER_PROFILE" for st in states.values()):
        return
    reported = parse_ts(row.get("reported_at"))
    audit_at = parse_ts(row.get("audit_at"))
    if reported is None:
        return
    path = dataset_dir / "system_activity.csv"
    best = None
    best_delta = None
    with path.open(newline="", encoding="utf-8") as handle:
        for activity in csv.DictReader(handle):
            if activity.get("event_type") != "DELETE_RECORD":
                continue
            if activity.get("target_system") != "account_service":
                continue
            when = parse_ts(activity.get("event_time"))
            if when is None:
                continue
            if audit_at and when > audit_at:
                continue
            delta = abs((when - reported).total_seconds())
            if best_delta is None or delta < best_delta:
                best_delta = delta
                best = activity
    if best is None or best_delta is None or best_delta > 15 * 60:
        return
    resource_id = best["resource_id"]
    # Cite the newest account-related evidence file at or before audit_at.
    evidence_id = ""
    newest = None
    for obs in store.observations:
        if obs.system_id != "account_service":
            continue
        if audit_at and obs.captured_at and obs.captured_at > audit_at:
            continue
        if newest is None or (obs.captured_at and newest.captured_at and obs.captured_at > newest.captured_at):
            newest = obs
    if newest:
        evidence_id = newest.file_id
    states[("account_service", resource_id)] = ResourceState(
        system_id="account_service",
        resource_id=resource_id,
        category="USER_PROFILE",
        present=False,
        pii_exposed=False,
        enabled=None,
        restore_allowed=None,
        evidence_id=evidence_id,
    )


def decisions_for_state(st: ResourceState, rules: dict[str, str]) -> tuple[list[str], list[str], list[str]]:
    """Return finding ops, remediation ops, verification ops for one resource."""
    findings: list[str] = []
    remediations: list[str] = []
    verifications: list[str] = []
    action = required_action(st.category, rules)

    if st.category == "DATA_FLOW":
        if st.enabled is True:
            findings.append("REPORT_ACTIVE_DATA_FLOW")
            remediations.append("DISABLE_DATA_FLOW")
        verifications.append("VERIFY_DATA_FLOW_DISABLED")
        return findings, remediations, verifications

    if st.category == "BACKUP_ARCHIVE":
        if st.restore_allowed is True:
            findings.append("REPORT_RESTORE_RISK")
            remediations.append("BLOCK_RESTORE")
        verifications.append("VERIFY_RESTORE_BLOCKED")
        return findings, remediations, verifications

    if action == "DELETE":
        if st.present:
            findings.append("REPORT_REMAINING_RECORD")
            remediations.append("DELETE_RECORD")
        verifications.append("VERIFY_RECORD_ABSENT")
        return findings, remediations, verifications

    if action == "REDACT":
        if st.present and st.pii_exposed:
            findings.append("REPORT_EXPOSED_PII")
            remediations.append("REDACT_RECORD")
        verifications.append("VERIFY_RECORD_REDACTED")
        return findings, remediations, verifications

    if action == "ANONYMIZE":
        if st.present and st.pii_exposed:
            findings.append("REPORT_EXPOSED_PII")
            remediations.append("ANONYMIZE_RECORD")
        verifications.append("VERIFY_RECORD_ANONYMIZED")
        return findings, remediations, verifications

    if action == "RETAIN":
        verifications.append("VERIFY_RECORD_PRESENT")
        return findings, remediations, verifications

    return findings, remediations, verifications


def _sort_ops(items: list[tuple[str, ResourceState]], order: list[str]) -> list[tuple[str, ResourceState]]:
    rank = {op: index for index, op in enumerate(order)}
    return sorted(items, key=lambda pair: (rank.get(pair[0], 99), pair[1].system_id, pair[1].resource_id))


def build_steps(
    states: dict[tuple[str, str], ResourceState],
    rules: dict[str, str],
) -> tuple[str, list[dict]]:
    findings: list[tuple[str, ResourceState]] = []
    remediations: list[tuple[str, ResourceState]] = []
    verifications: list[tuple[str, ResourceState]] = []
    for st in states.values():
        f_ops, r_ops, v_ops = decisions_for_state(st, rules)
        findings.extend((op, st) for op in f_ops)
        remediations.extend((op, st) for op in r_ops)
        verifications.extend((op, st) for op in v_ops)

    findings = _sort_ops(findings, FINDING_OPS)
    remediations = _sort_ops(remediations, REMEDIATION_OPS)
    verifications = _sort_ops(verifications, VERIFICATION_OPS)

    incomplete = bool(findings)
    steps: list[dict] = []
    number = 1

    def add(phase: str, op: str, st: ResourceState, evidence: str) -> None:
        nonlocal number
        steps.append(
            {
                "step_no": number,
                "phase": phase,
                "system_id": st.system_id,
                "resource_id": st.resource_id,
                "operation": op,
                "state": OP_STATE[op],
                "evidence_id": evidence,
            }
        )
        number += 1

    if incomplete:
        for op, st in findings:
            add("FINDING", op, st, st.evidence_id)
        for op, st in remediations:
            add("REMEDIATION", op, st, "")
        for op, st in verifications:
            add("VERIFICATION", op, st, "")
        return "INCOMPLETE", steps

    for op, st in verifications:
        add("VERIFICATION", op, st, st.evidence_id)
    return "COMPLETE", steps


def plan_case(
    row: dict,
    person: ResolvedIdentity | None,
    is_deletion: bool,
    store: EvidenceStore,
    rules: dict[str, str],
    dataset_dir: Path,
) -> tuple[str, list[dict]]:
    if not is_deletion:
        return "NOT_APPLICABLE", []
    if person is None:
        return "INCOMPLETE", []
    audit_at = parse_ts(row.get("audit_at"))
    hits = store.for_person(person, audit_at)
    states = _latest_states(hits)
    _maybe_account_from_activity(dataset_dir, row, states, store)
    return build_steps(states, rules)


def steps_to_json(steps: list[dict]) -> str:
    return json.dumps(steps, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
