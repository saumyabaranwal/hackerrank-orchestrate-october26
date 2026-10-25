#!/usr/bin/env python3
"""Ghost Data Still Exists — deletion-audit agent entry point.

From the cloned challenge repo (dataset/ next to code/):

    python3 code/main.py
    python3 code/main.py --dataset dataset --out output.csv

From an unzipped code.zip sitting beside dataset/:

    python3 main.py --dataset ../dataset --out ../output.csv
"""

from __future__ import annotations

import sys
from pathlib import Path

CODE_DIR = Path(__file__).resolve().parent
if str(CODE_DIR) not in sys.path:
    sys.path.insert(0, str(CODE_DIR))

from agent.pipeline import (  # noqa: E402
    format_inspect_table,
    inspect_evidence,
    inspect_requests,
    plan_requests,
    score_sample,
    write_output,
)


def _flag_value(args: list[str], name: str) -> str | None:
    if name not in args:
        return None
    idx = args.index(name)
    if idx + 1 >= len(args) or args[idx + 1].startswith("--"):
        raise SystemExit(f"{name} needs a path argument")
    return args[idx + 1]


def _case_id(args: list[str]) -> str | None:
    for arg in args:
        if arg.startswith("case_"):
            return arg
    return None


def find_dataset(cli: str | None) -> Path:
    """Locate dataset/ even if the judge unzipped code.zip alone."""
    if cli:
        path = Path(cli).expanduser().resolve()
        if not (path / "deletion_requests.csv").exists():
            raise SystemExit(f"No deletion_requests.csv under {path}")
        return path
    here = Path(__file__).resolve().parent
    cwd = Path.cwd()
    candidates = [
        cwd / "dataset",
        here.parent / "dataset",  # repo root when running code/main.py
        here / "dataset",
        cwd.parent / "dataset",
        Path("/home/user/dataset"),
    ]
    for candidate in candidates:
        if (candidate / "deletion_requests.csv").exists():
            return candidate.resolve()
    raise SystemExit(
        "Cannot find dataset/deletion_requests.csv. "
        "Pass --dataset PATH (the folder that contains deletion_requests.csv)."
    )


def find_output(cli: str | None, dataset: Path) -> Path:
    if cli:
        return Path(cli).expanduser().resolve()
    # Prefer the challenge repo root (parent of dataset/) so output.csv
    # lands where the submission template lives.
    repo = dataset.parent
    if (repo / "dataset").exists() or (repo / "AGENTS.md").exists():
        return repo / "output.csv"
    return Path.cwd() / "output.csv"


def main() -> None:
    args = [a for a in sys.argv[1:] if a != "--run"]
    if "--help" in args or "-h" in args:
        print("Commands:")
        print("  python3 code/main.py")
        print("  python3 code/main.py --dataset PATH --out PATH")
        print("  python3 code/main.py --skeleton")
        print("  python3 code/main.py --evidence case_05")
        print("  python3 code/main.py --plan case_05")
        print("  python3 code/main.py --score-sample")
        print("dataset/ is auto-detected next to code/ or via --dataset.")
        return

    dataset = find_dataset(_flag_value(args, "--dataset"))
    dest = find_output(_flag_value(args, "--out"), dataset)
    sample = dataset / "sample_deletion_requests.csv"

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
    print(write_output(dataset, dest))


if __name__ == "__main__":
    main()
