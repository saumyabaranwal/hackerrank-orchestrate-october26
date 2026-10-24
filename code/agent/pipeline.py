"""The boss.

classify → identity → evidence → policy → planner
"""

from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path

import json

from .classify import is_deletion_request
from .evidence import EvidenceStore, Observation
from .identity import IdentityIndex, ResolvedIdentity
from .parsers import parse_ts
from .planner import plan_case, steps_to_json
from .policy import load_rules


@dataclass
class SkeletonResult:
    case_id: str
    request_email: str
    is_deletion: bool
    status_if_we_stopped_here: str
    identity: ResolvedIdentity | None


def inspect_requests(dataset_dir: Path, requests_csv: Path) -> list[SkeletonResult]:
    index = IdentityIndex(dataset_dir)
    results: list[SkeletonResult] = []
    with requests_csv.open(newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            deletion = is_deletion_request(row.get("request_text") or "")
            identity = index.resolve(row.get("email") or "")
            status = "NOT_APPLICABLE" if not deletion else "DELETION_AUTHORIZED"
            results.append(
                SkeletonResult(
                    case_id=row["case_id"],
                    request_email=row.get("email") or "",
                    is_deletion=deletion,
                    status_if_we_stopped_here=status,
                    identity=identity,
                )
            )
    return results


def format_inspect_table(results: list[SkeletonResult]) -> str:
    lines = [
        f"{'case':<10} {'deletion?':<12} {'match':<18} {'user_id':<12} {'name':<22} emails",
        "-" * 110,
    ]
    for item in results:
        ident = item.identity
        user_id = ident.user_id if ident else "UNRESOLVED"
        name = ident.name if ident else "-"
        match = ident.matched_on if ident else "-"
        extra = ""
        if ident:
            old = sorted(e for e in ident.emails if e != ident.current_email.lower())
            extra = ident.current_email
            if old:
                extra += " | old: " + ", ".join(old)
        lines.append(
            f"{item.case_id:<10} {str(item.is_deletion):<12} {match:<18} {user_id:<12} {name:<22} {extra}"
        )
    authorized = sum(1 for item in results if item.is_deletion)
    unresolved = sum(1 for item in results if item.identity is None)
    historical = sum(
        1 for item in results if item.identity and item.identity.matched_on == "historical_email"
    )
    lines.append("-" * 110)
    lines.append(
        f"{len(results)} cases | {authorized} deletion | "
        f"{len(results) - authorized} not-applicable | "
        f"{historical} matched on OLD email | {unresolved} unresolved"
    )
    return "\n".join(lines)


def _latest_per_resource(hits: list[Observation]) -> list[Observation]:
    """One row per (system, resource): the newest file still allowed by audit_at."""
    best: dict[tuple[str, str], Observation] = {}
    for obs in hits:
        key = (obs.system_id, obs.resource_id)
        previous = best.get(key)
        if previous is None:
            best[key] = obs
            continue
        prev_ts = previous.captured_at or previous.observed_at
        new_ts = obs.captured_at or obs.observed_at
        if prev_ts is None or (new_ts is not None and new_ts >= prev_ts):
            # Replica ghost: if ANY copy at this time is present, keep present.
            if obs.present or not previous.present:
                best[key] = obs
    return sorted(best.values(), key=lambda item: (item.system_id, item.resource_id))


def inspect_evidence(
    dataset_dir: Path,
    requests_csv: Path,
    case_id: str | None = None,
) -> str:
    index = IdentityIndex(dataset_dir)
    store = EvidenceStore(dataset_dir)
    lines = [
        f"Evidence cabinet loaded: {len(store.observations)} observations "
        f"from {len(store.manifest)} files.",
        "",
    ]
    with requests_csv.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    selected = [row for row in rows if case_id is None or row["case_id"] == case_id]
    if not selected:
        return f"No case named {case_id}."

    for row in selected:
        person = index.resolve(row.get("email") or "")
        audit_at = parse_ts(row.get("audit_at"))
        lines.append("=" * 88)
        lines.append(
            f"{row['case_id']}  email={row.get('email')}  "
            f"audit_at={row.get('audit_at')}  reported={row.get('reported_status')}"
        )
        if person is None:
            lines.append("  identity: UNRESOLVED")
            continue
        lines.append(
            f"  identity: {person.user_id}  {person.name}  "
            f"match={person.matched_on}  emails={sorted(person.emails)}"
        )
        hits = store.for_person(person, audit_at)
        latest = _latest_per_resource(hits)
        lines.append(f"  raw hits={len(hits)}  unique resources={len(latest)}")
        lines.append(
            f"  {'system':<24} {'resource':<22} {'category':<22} {'flags':<28} evidence"
        )
        for obs in latest:
            lines.append(
                f"  {obs.system_id:<24} {obs.resource_id:<22} {obs.category:<22} "
                f"{obs.summary():<28} {obs.file_id}"
            )
        if not latest:
            lines.append("  (nothing linked yet — absence of a profile is also a finding later)")
    return "\n".join(lines)


def plan_requests(dataset_dir: Path, requests_csv: Path, case_id: str | None = None) -> str:
    index = IdentityIndex(dataset_dir)
    store = EvidenceStore(dataset_dir)
    rules = load_rules(dataset_dir)
    lines: list[str] = []
    with requests_csv.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    selected = [row for row in rows if case_id is None or row["case_id"] == case_id]
    for row in selected:
        deletion = is_deletion_request(row.get("request_text") or "")
        person = index.resolve(row.get("email") or "")
        status, steps = plan_case(row, person, deletion, store, rules, dataset_dir)
        lines.append("=" * 88)
        lines.append(f"{row['case_id']}  {status}  steps={len(steps)}")
        for step in steps:
            lines.append(
                f"  {step['step_no']:2} {step['phase']:<12} {step['operation']:<28} "
                f"{step['system_id']:<22} {step['resource_id']:<20} ev={step['evidence_id']!r}"
            )
        if not steps:
            lines.append("  []")
    return "\n".join(lines)


def _step_sig(steps: list[dict]) -> list[tuple]:
    return [
        (s.get("phase"), s.get("operation"), s.get("system_id"), s.get("resource_id"), s.get("state"))
        for s in steps
    ]


def score_sample(dataset_dir: Path) -> str:
    index = IdentityIndex(dataset_dir)
    store = EvidenceStore(dataset_dir)
    rules = load_rules(dataset_dir)
    requests_csv = dataset_dir / "sample_deletion_requests.csv"
    gold_csv = dataset_dir / "sample_output.csv"
    with gold_csv.open(newline="", encoding="utf-8") as handle:
        gold = {row["case_id"]: row for row in csv.DictReader(handle)}
    status_ok = 0
    structure_ok = 0
    lines: list[str] = []
    with requests_csv.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    for row in rows:
        deletion = is_deletion_request(row.get("request_text") or "")
        person = index.resolve(row.get("email") or "")
        status, steps = plan_case(row, person, deletion, store, rules, dataset_dir)
        expected = gold[row["case_id"]]
        expected_status = expected["deletion_status"]
        expected_steps = json.loads(expected["steps_json"])
        same_status = status == expected_status
        same_struct = _step_sig(steps) == _step_sig(expected_steps)
        if same_status:
            status_ok += 1
        if same_status and same_struct:
            structure_ok += 1
        mark = "OK" if same_status and same_struct else ("STATUS" if same_status else "MISS")
        if mark != "OK":
            lines.append(f"{row['case_id']} {mark} pred={status} gold={expected_status}")
            lines.append(f"  pred {_step_sig(steps)}")
            lines.append(f"  gold {_step_sig(expected_steps)}")
    lines.append("-" * 72)
    lines.append(
        f"status {status_ok}/{len(rows)}  structure {structure_ok}/{len(rows)}  "
        f"obs={len(store.observations)}"
    )
    return "\n".join(lines)
