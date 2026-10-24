#!/usr/bin/env python3
"""Ghost Data Still Exists — deletion-audit agent entry point.

    python3 code/main.py --skeleton
    python3 code/main.py --evidence case_05
    python3 code/main.py --plan case_05
    python3 code/main.py --score-sample
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CODE_DIR = Path(__file__).resolve().parent
if str(CODE_DIR) not in sys.path:
    sys.path.insert(0, str(CODE_DIR))

from agent.pipeline import (  # noqa: E402
    format_inspect_table,
    inspect_evidence,
    inspect_requests,
    plan_requests,
    score_sample,
)


def _case_id(args: list[str]) -> str | None:
    for arg in args:
        if arg.startswith("case_"):
            return arg
    return None


def main() -> None:
    dataset = ROOT / "dataset"
    sample = dataset / "sample_deletion_requests.csv"
    args = sys.argv[1:]

    if "--skeleton" in args:
        print(format_inspect_table(inspect_requests(dataset, sample)))
        return
    if "--evidence" in args:
        print(inspect_evidence(dataset, sample, case_id=_case_id(args)))
        return
    if "--plan" in args:
        print(plan_requests(dataset, sample, case_id=_case_id(args)))
        return
    if "--score-sample" in args:
        print(score_sample(dataset))
        return

    print("Commands:")
    print("  python3 code/main.py --skeleton")
    print("  python3 code/main.py --evidence case_05")
    print("  python3 code/main.py --plan case_05")
    print("  python3 code/main.py --score-sample")


if __name__ == "__main__":
    main()
