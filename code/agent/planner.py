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

from .classify import is_deletion_request
from .evidence import EvidenceStore, Observation
from .identity import IdentityIndex, ResolvedIdentity
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
        def _ts(item: Observation):
            return item.file_captured_at or item.captured_at or item.observed_at or datetime.min

        latest_cap = max((_ts(item) for item in items), default=datetime.min)
        latest = [item for item in items if _ts(item) == latest_cap]
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


def _file_time(obs: Observation):
    return obs.file_captured_at or obs.captured_at


def _newest_system_evidence(store: EvidenceStore, system_id: str, audit_at) -> str:
    newest = None
    for obs in store.observations:
        if obs.system_id != system_id:
            continue
        cap = _file_time(obs)
        if audit_at and cap and cap > audit_at:
            continue
        if newest is None:
            newest = obs
            continue
        prev = _file_time(newest)
        if prev is None or (cap is not None and cap >= prev):
            newest = obs
    return newest.file_id if newest else ""


def _ownership_map(store: EvidenceStore, index: IdentityIndex) -> dict[str, set[str]]:
    """resource_id -> user_ids that ever appeared with identifiers on it."""
    owned: dict[str, set[str]] = {}
    for obs in store.observations:
        uids: set[str] = set()
        for email in obs.emails:
            uid = index.email_to_user.get(email)
            if uid:
                uids.add(uid)
        for uid in obs.user_ids:
            if uid in index.by_user_id:
                uids.add(uid)
        if not uids:
            continue
        owned.setdefault(obs.resource_id, set()).update(uids)
    return owned


def _keep_one_account(
    states: dict[tuple[str, str], ResourceState],
    store: EvidenceStore,
    person: ResolvedIdentity,
    hits: list[Observation],
) -> None:
    """A person has one live profile. Historical 404 lookups for other
    account_ids are noise — keep the one we saw most recently at audit."""
    accounts = [(key, st) for key, st in states.items() if st.category == "USER_PROFILE"]
    if len(accounts) <= 1:
        return
    seen_at_audit = {(obs.system_id, obs.resource_id) for obs in hits if obs.category == "USER_PROFILE"}
    meta = store.latest_any_time(person)

    def recency(key: tuple[str, str]):
        at_audit = 1 if key in seen_at_audit else 0
        obs = meta.get(key)
        ts = datetime.min
        if obs is not None:
            ts = _file_time(obs) or obs.observed_at or datetime.min
        return (at_audit, ts, key[1])

    accounts.sort(key=lambda pair: recency(pair[0]), reverse=True)
    for key, _st in accounts[1:]:
        states.pop(key, None)


def _synthesize_owned_missing(
    person: ResolvedIdentity,
    states: dict[tuple[str, str], ResourceState],
    store: EvidenceStore,
    audit_at,
) -> None:
    """If a later file taught us this resource belongs to the person, but
    nothing at audit_at mentioned it, still verify it.

    Gone profiles are ABSENT (not in the at-audit snapshots).
    Audit logs are retained PRESENT.
    """
    meta = store.latest_any_time(person)
    for key, obs in meta.items():
        if key in states:
            continue
        if obs.category == "USER_PROFILE":
            states[key] = ResourceState(
                system_id=obs.system_id,
                resource_id=obs.resource_id,
                category="USER_PROFILE",
                present=False,
                pii_exposed=False,
                enabled=None,
                restore_allowed=None,
                evidence_id=_newest_system_evidence(store, "account_service", audit_at),
            )
        elif obs.category == "SECURITY_AUDIT_LOG":
            states[key] = ResourceState(
                system_id=obs.system_id,
                resource_id=obs.resource_id,
                category="SECURITY_AUDIT_LOG",
                present=True,
                pii_exposed=False,
                enabled=None,
                restore_allowed=None,
                evidence_id=_newest_system_evidence(store, "security_service", audit_at),
            )


def _load_activity(dataset_dir: Path) -> list[dict]:
    path = dataset_dir / "system_activity.csv"
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


# An event may attach to a request only if that request is clearly closer
# than any other deletion request (not merely the closest on a busy morning).
_ASSIGN_WINDOW = 2 * 60 * 60
_ASSIGN_MARGIN = 10 * 60


def _all_request_rows(dataset_dir: Path) -> list[dict]:
    """Sample cases are not inside the 518-row file. Matching must see both
    so a sample user's DELETE is not given to a nearby eval case, and vice versa.
    """
    seen: set[str] = set()
    rows: list[dict] = []
    for name in ("deletion_requests.csv", "sample_deletion_requests.csv"):
        path = dataset_dir / name
        if not path.exists():
            continue
        with path.open(newline="", encoding="utf-8") as handle:
            for row in csv.DictReader(handle):
                case_id = row.get("case_id") or ""
                if case_id in seen:
                    continue
                seen.add(case_id)
                rows.append(row)
    return rows


def _evidence_states(
    row: dict,
    person: ResolvedIdentity,
    store: EvidenceStore,
) -> dict[tuple[str, str], ResourceState]:
    audit_at = parse_ts(row.get("audit_at"))
    hits = store.for_person(person, audit_at)
    states = _latest_states(hits)
    _synthesize_owned_missing(person, states, store, audit_at)
    _keep_one_account(states, store, person, hits)
    return states


def _assign_unique_events(
    events: list[dict],
    needers: list[dict],
    owned: dict[str, set[str]],
) -> dict[str, str]:
    """Map case_id -> resource_id. Skip the event if two requests are within
    MARGIN seconds of each other; each case keeps at most one resource.
    """
    tentative: list[tuple[float, str, str]] = []  # delta, case_id, resource_id
    for event in events:
        rid = event.get("resource_id") or ""
        when = parse_ts(event.get("event_time"))
        if not rid or when is None:
            continue
        owners = owned.get(rid, set())
        scored: list[tuple[float, str]] = []
        for case in needers:
            if owners and case["user_id"] not in owners:
                continue
            audit_at = case["audit_at"]
            reported = case["reported"]
            if reported is None:
                continue
            if audit_at and when > audit_at:
                continue
            delta = abs((when - reported).total_seconds())
            if delta > _ASSIGN_WINDOW:
                continue
            scored.append((delta, case["case_id"]))
        if not scored:
            continue
        scored.sort()
        best_delta, best_case = scored[0]
        second = scored[1][0] if len(scored) > 1 else None
        if second is not None and not (best_delta + _ASSIGN_MARGIN < second):
            continue
        tentative.append((best_delta, best_case, rid))

    by_case: dict[str, tuple[float, str]] = {}
    used_resources: set[str] = set()
    tentative.sort()
    for delta, case_id, rid in tentative:
        if case_id in by_case or rid in used_resources:
            continue
        by_case[case_id] = (delta, rid)
        used_resources.add(rid)
    return {case_id: rid for case_id, (_delta, rid) in by_case.items()}


def _build_activity_claims(
    dataset_dir: Path,
    store: EvidenceStore,
    index: IdentityIndex,
    activities: list[dict],
    owned: dict[str, set[str]],
) -> dict[str, dict[str, str]]:
    """case_id -> {account_id?, analytics_id?} from unambiguous activity only."""
    need_account: list[dict] = []
    need_analytics: list[dict] = []
    for row in _all_request_rows(dataset_dir):
        if not is_deletion_request(row.get("request_text") or ""):
            continue
        person = index.resolve(row.get("email") or "")
        if person is None:
            continue
        states = _evidence_states(row, person, store)
        meta = {
            "case_id": row["case_id"],
            "user_id": person.user_id,
            "reported": parse_ts(row.get("reported_at")),
            "audit_at": parse_ts(row.get("audit_at")),
        }
        if not any(st.category == "USER_PROFILE" for st in states.values()):
            need_account.append(meta)
        if not any(st.category == "ANALYTICS_PROFILE" for st in states.values()):
            need_analytics.append(meta)

    account_events = [
        event for event in activities
        if event.get("event_type") == "DELETE_RECORD"
        and event.get("target_system") == "account_service"
    ]
    analytics_events = [
        event for event in activities
        if event.get("event_type") == "ANONYMIZE_RECORD"
        and event.get("target_system") == "analytics_platform"
    ]
    accounts = _assign_unique_events(account_events, need_account, owned)
    analytics = _assign_unique_events(analytics_events, need_analytics, owned)
    claims: dict[str, dict[str, str]] = {}
    for case_id, rid in accounts.items():
        claims.setdefault(case_id, {})["account_id"] = rid
    for case_id, rid in analytics.items():
        claims.setdefault(case_id, {})["analytics_id"] = rid
    return claims


def _apply_activity_claim(
    claim: dict[str, str] | None,
    states: dict[tuple[str, str], ResourceState],
    store: EvidenceStore,
    audit_at,
) -> None:
    if not claim:
        return
    account_id = claim.get("account_id")
    if account_id and not any(st.category == "USER_PROFILE" for st in states.values()):
        states[("account_service", account_id)] = ResourceState(
            system_id="account_service",
            resource_id=account_id,
            category="USER_PROFILE",
            present=False,
            pii_exposed=False,
            enabled=None,
            restore_allowed=None,
            evidence_id=_newest_system_evidence(store, "account_service", audit_at),
        )
    analytics_id = claim.get("analytics_id")
    if analytics_id and not any(st.category == "ANALYTICS_PROFILE" for st in states.values()):
        states[("analytics_platform", analytics_id)] = ResourceState(
            system_id="analytics_platform",
            resource_id=analytics_id,
            category="ANALYTICS_PROFILE",
            present=True,
            pii_exposed=False,
            enabled=None,
            restore_allowed=None,
            evidence_id=_newest_system_evidence(store, "analytics_platform", audit_at),
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


_ACTIVITY_BY_DIR: dict[Path, list[dict]] = {}
_OWNED_BY_STORE: dict[int, dict[str, set[str]]] = {}
_CLAIMS_BY_STORE: dict[int, dict[str, dict[str, str]]] = {}


def _claims_for(
    dataset_dir: Path,
    store: EvidenceStore,
    index: IdentityIndex | None,
) -> dict[str, dict[str, str]]:
    if index is None:
        return {}
    cached = _CLAIMS_BY_STORE.get(id(store))
    if cached is not None:
        return cached
    activities = _ACTIVITY_BY_DIR.get(dataset_dir)
    if activities is None:
        activities = _load_activity(dataset_dir)
        _ACTIVITY_BY_DIR[dataset_dir] = activities
    owned = _OWNED_BY_STORE.get(id(store))
    if owned is None:
        owned = _ownership_map(store, index)
        _OWNED_BY_STORE[id(store)] = owned
    claims = _build_activity_claims(dataset_dir, store, index, activities, owned)
    _CLAIMS_BY_STORE[id(store)] = claims
    return claims


def plan_case(
    row: dict,
    person: ResolvedIdentity | None,
    is_deletion: bool,
    store: EvidenceStore,
    rules: dict[str, str],
    dataset_dir: Path,
    index: IdentityIndex | None = None,
) -> tuple[str, list[dict]]:
    if not is_deletion:
        return "NOT_APPLICABLE", []
    if person is None:
        return "INCOMPLETE", []
    audit_at = parse_ts(row.get("audit_at"))
    hits = store.for_person(person, audit_at)
    states = _latest_states(hits)
    _synthesize_owned_missing(person, states, store, audit_at)
    _keep_one_account(states, store, person, hits)
    claim = _claims_for(dataset_dir, store, index).get(row["case_id"])
    _apply_activity_claim(claim, states, store, audit_at)
    return build_steps(states, rules)


def steps_to_json(steps: list[dict]) -> str:
    return json.dumps(steps, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
