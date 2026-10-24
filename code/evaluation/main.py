#!/usr/bin/env python3
"""Team evaluation runner.

    python3 code/evaluation/main.py

Scores the 32 public sample cases against sample_output.csv and runs three
additional probes we designed (classifier N/A, historical identity, extra-id
precision). Does not read organizer-only files.
"""

from __future__ import annotations

import csv
import json
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
CODE_DIR = Path(__file__).resolve().parent.parent
if str(CODE_DIR) not in sys.path:
    sys.path.insert(0, str(CODE_DIR))

from agent.classify import is_deletion_request  # noqa: E402
from agent.evidence import EvidenceStore  # noqa: E402
from agent.identity import IdentityIndex  # noqa: E402
from agent.planner import plan_case  # noqa: E402
from agent.policy import load_rules  # noqa: E402


def _sig(steps: list[dict]) -> list[tuple]:
    return [
        (s.get("phase"), s.get("operation"), s.get("system_id"), s.get("resource_id"), s.get("state"))
        for s in steps
    ]


def score_public_sample(dataset: Path) -> dict:
    index = IdentityIndex(dataset)
    store = EvidenceStore(dataset)
    rules = load_rules(dataset)
    gold = {row["case_id"]: row for row in csv.DictReader((dataset / "sample_output.csv").open(newline="", encoding="utf-8"))}
    rows = list(csv.DictReader((dataset / "sample_deletion_requests.csv").open(newline="", encoding="utf-8")))
    status_ok = struct_ok = 0
    extra = miss = 0
    n_pred = n_gold = 0
    field_hits: Counter[str] = Counter()
    field_tot: Counter[str] = Counter()
    fields = ("phase", "operation", "system_id", "resource_id", "state")
    for row in rows:
        deletion = is_deletion_request(row.get("request_text") or "")
        person = index.resolve(row.get("email") or "")
        status, steps = plan_case(row, person, deletion, store, rules, dataset, index)
        expected = gold[row["case_id"]]
        gold_steps = json.loads(expected["steps_json"])
        n_pred += len(steps)
        n_gold += len(gold_steps)
        if status == expected["deletion_status"]:
            status_ok += 1
        if status == expected["deletion_status"] and _sig(steps) == _sig(gold_steps):
            struct_ok += 1
        pb = Counter((s["system_id"], s["resource_id"], s["operation"]) for s in steps)
        gb = Counter((s["system_id"], s["resource_id"], s["operation"]) for s in gold_steps)
        extra += sum((pb - gb).values())
        miss += sum((gb - pb).values())
        for pred, gold_step in zip(steps, gold_steps):
            for field in fields:
                field_tot[field] += 1
                if pred.get(field) == gold_step.get(field):
                    field_hits[field] += 1
    return {
        "n": len(rows),
        "status_ok": status_ok,
        "struct_ok": struct_ok,
        "extra": extra,
        "miss": miss,
        "n_pred": n_pred,
        "n_gold": n_gold,
        "field_hits": dict(field_hits),
        "field_tot": dict(field_tot),
    }


def team_case_non_deletion() -> tuple[bool, str]:
    """Team case 1 — a non-deletion request must never authorize erasure."""
    texts = [
        "I am not asking for deletion. Please send a copy of last year's invoices.",
        "The mobile number on my profile is out of date.",
        "Please download my account information without removing any of my records.",
        "Stop the promotional emails. Leave the account active.",
    ]
    failed = [text for text in texts if is_deletion_request(text)]
    if failed:
        return False, f"classifier treated non-deletion as deletion: {failed[0][:60]}"
    return True, "4 non-deletion texts → NOT_APPLICABLE / not authorized"


def team_case_historical_identity(dataset: Path) -> tuple[bool, str]:
    """Team case 2 — request email may be historical; collect every identifier."""
    index = IdentityIndex(dataset)
    person = index.resolve("camille.bernard86@outlook.com")
    if person is None:
        return False, "historical email did not resolve"
    if person.user_id != "user_30":
        return False, f"resolved {person.user_id}, expected user_30"
    if "camille.bernard@outlook.com" not in person.emails:
        return False, "old email missing from identity set"
    if person.matched_on != "historical_email":
        return False, f"matched_on={person.matched_on}"
    return True, "user_30 resolved from old address; both emails collected"


def team_case_no_stolen_accounts(dataset: Path) -> tuple[bool, str]:
    """Team case 3 — busy-morning DELETEs must not attach a neighbour's account."""
    index = IdentityIndex(dataset)
    store = EvidenceStore(dataset)
    rules = load_rules(dataset)
    rows = {
        row["case_id"]: row
        for row in csv.DictReader((dataset / "sample_deletion_requests.csv").open(newline="", encoding="utf-8"))
    }
    forbidden = {
        "case_17": "account_6523",  # old extra 404 for the same email
        "case_18": "account_5193",  # closer in time, different owner
    }
    stolen = []
    for case_id, resource_id in forbidden.items():
        row = rows[case_id]
        deletion = is_deletion_request(row.get("request_text") or "")
        person = index.resolve(row.get("email") or "")
        _status, steps = plan_case(row, person, deletion, store, rules, dataset, index)
        if any(step.get("resource_id") == resource_id for step in steps):
            stolen.append(f"{case_id}:{resource_id}")
    if stolen:
        return False, "stole " + ", ".join(stolen)
    return True, "case_17/18 did not emit neighbour account ids"


def main() -> None:
    dataset = ROOT / "dataset"
    print("Public sample (32 cases vs sample_output.csv)")
    sample = score_public_sample(dataset)
    print(
        f"  status {sample['status_ok']}/{sample['n']}  "
        f"exact structure {sample['struct_ok']}/{sample['n']}  "
        f"extra_steps={sample['extra']} missed_steps={sample['miss']}  "
        f"pred_steps={sample['n_pred']} gold_steps={sample['n_gold']}"
    )
    print("Team additional cases")
    cases = [
        ("TC1 non-deletion classifier", team_case_non_deletion()),
        ("TC2 historical identity", team_case_historical_identity(dataset)),
        ("TC3 no stolen accounts", team_case_no_stolen_accounts(dataset)),
    ]
    failed = 0
    for name, (ok, detail) in cases:
        mark = "PASS" if ok else "FAIL"
        if not ok:
            failed += 1
        print(f"  {mark}  {name}: {detail}")
    if failed:
        sys.exit(1)


if __name__ == "__main__":
    main()
