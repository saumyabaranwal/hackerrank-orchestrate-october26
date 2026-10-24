"""Brain 3 — the filing cabinet.

The agent is not allowed to believe dashboards. It opens every evidence
file, turns it into the same shape (an Observation), then asks:

    "For THIS person, at THIS audit time, what records exist?"
"""

from __future__ import annotations

import csv
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

from .identity import ResolvedIdentity
from .parsers import parse_evidence_file, parse_ts


@dataclass
class Observation:
    file_id: str
    captured_at: Optional[datetime]
    observed_at: Optional[datetime]
    system_id: str
    resource_id: str
    category: str
    emails: set[str]
    user_ids: set[str]
    phones: set[str]
    hashes: set[str]
    present: Optional[bool]
    pii_exposed: Optional[bool]
    enabled: Optional[bool]
    restore_allowed: Optional[bool]
    replica_role: str

    def matches(self, person: ResolvedIdentity) -> bool:
        if person.user_id and person.user_id in self.user_ids:
            return True
        if self.emails & person.emails:
            return True
        if self.hashes & person.hashes:
            return True
        if self.phones & person.phones:
            return True
        return False

    def summary(self) -> str:
        flags = []
        if self.present is True:
            flags.append("PRESENT")
        elif self.present is False:
            flags.append("ABSENT")
        if self.pii_exposed:
            flags.append("PII")
        if self.enabled is True:
            flags.append("FLOW_ON")
        if self.enabled is False:
            flags.append("FLOW_OFF")
        if self.restore_allowed is True:
            flags.append("RESTORE_OPEN")
        if self.restore_allowed is False:
            flags.append("RESTORE_BLOCKED")
        if self.replica_role != "unknown":
            flags.append(self.replica_role.upper())
        return ",".join(flags) or "-"


def _from_dict(raw: dict[str, Any]) -> Observation:
    return Observation(
        file_id=raw["file_id"],
        captured_at=raw.get("captured_at"),
        observed_at=raw.get("observed_at"),
        system_id=raw["system_id"],
        resource_id=raw["resource_id"],
        category=raw["category"],
        emails=set(raw.get("emails") or []),
        user_ids=set(raw.get("user_ids") or []),
        phones=set(raw.get("phones") or []),
        hashes=set(raw.get("hashes") or []),
        present=raw.get("present"),
        pii_exposed=raw.get("pii_exposed"),
        enabled=raw.get("enabled"),
        restore_allowed=raw.get("restore_allowed"),
        replica_role=raw.get("replica_role") or "unknown",
    )


class EvidenceStore:
    """Load once, search many times. That is the agent's memory of the world."""

    def __init__(self, dataset_dir: Path) -> None:
        self.dataset_dir = dataset_dir
        self.observations: list[Observation] = []
        self.manifest: dict[str, dict[str, str]] = {}
        self._load_manifest()
        self._parse_all()

    def _load_manifest(self) -> None:
        path = self.dataset_dir / "evidence_files.csv"
        with path.open(newline="", encoding="utf-8") as handle:
            for row in csv.DictReader(handle):
                self.manifest[row["file_id"]] = row

    def _parse_all(self) -> None:
        for file_id, meta in self.manifest.items():
            captured = parse_ts(meta.get("captured_at"))
            rel = meta.get("file_path") or ""
            path = self.dataset_dir / rel
            for raw in parse_evidence_file(path, file_id, captured):
                self.observations.append(_from_dict(raw))

    def for_person(self, person: ResolvedIdentity, audit_at: datetime | None) -> list[Observation]:
        """Everything we can prove belongs to this person at or before audit_at.

        Pass 1: match on email / user_id / hash / phone.
        Pass 2: keep later snapshots of the SAME resource even if identifiers
        were already stripped (anonymized analytics, redacted tickets).
        """
        def allowed(obs: Observation) -> bool:
            if audit_at and obs.captured_at and obs.captured_at > audit_at:
                return False
            return True

        linked: set[tuple[str, str]] = set()
        hits: list[Observation] = []
        for obs in self.observations:
            if not allowed(obs):
                continue
            if obs.matches(person):
                linked.add((obs.system_id, obs.resource_id))
                hits.append(obs)
        for obs in self.observations:
            if not allowed(obs):
                continue
            if (obs.system_id, obs.resource_id) in linked and obs not in hits:
                hits.append(obs)
        hits.sort(key=lambda item: (item.system_id, item.resource_id, item.file_id))
        return hits
