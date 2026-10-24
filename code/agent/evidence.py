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
    file_captured_at: Optional[datetime] = None

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
                obs = _from_dict(raw)
                obs.file_captured_at = captured
                self.observations.append(obs)

    def _file_time(self, obs: Observation) -> Optional[datetime]:
        """When the evidence file was captured — that is the audit clock.

        Nested snapshot timestamps say when a row was true inside a later
        export; they must not leak a Sep-17 file into a Sep-15 audit.
        """
        return obs.file_captured_at or obs.captured_at

    def linked_keys(self, person: ResolvedIdentity) -> set[tuple[str, str]]:
        """Resource keys that ever carried this person's identifiers.

        Ownership is stable (an account_id does not jump to someone else),
        so a later file may teach us the id even when the at-audit snapshot
        is a bare 404.
        """
        linked: set[tuple[str, str]] = set()
        for obs in self.observations:
            if obs.matches(person):
                linked.add((obs.system_id, obs.resource_id))
        return linked

    def latest_any_time(self, person: ResolvedIdentity) -> dict[tuple[str, str], Observation]:
        """Newest observation of each linked resource, ignoring audit_at."""
        linked = self.linked_keys(person)
        best: dict[tuple[str, str], Observation] = {}
        for obs in self.observations:
            key = (obs.system_id, obs.resource_id)
            if key not in linked:
                continue
            previous = best.get(key)
            if previous is None:
                best[key] = obs
                continue
            prev_ts = previous.file_captured_at or previous.captured_at or previous.observed_at
            new_ts = obs.file_captured_at or obs.captured_at or obs.observed_at
            if prev_ts is None or (new_ts is not None and new_ts >= prev_ts):
                best[key] = obs
        return best

    def for_person(self, person: ResolvedIdentity, audit_at: datetime | None) -> list[Observation]:
        """State of this person's resources at or before audit_at.

        Pass 1: match identifiers in ANY file (ownership).
        Pass 2: keep at-audit snapshots of those resources even if the
        identifiers were already stripped (anonymized analytics, 404s).
        """
        linked = self.linked_keys(person)

        def allowed(obs: Observation) -> bool:
            cap = self._file_time(obs)
            if audit_at and cap and cap > audit_at:
                return False
            return True

        hits: list[Observation] = []
        for obs in self.observations:
            if not allowed(obs):
                continue
            if (obs.system_id, obs.resource_id) in linked:
                hits.append(obs)
        hits.sort(key=lambda item: (item.system_id, item.resource_id, item.file_id))
        return hits
