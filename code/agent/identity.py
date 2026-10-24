"""Brain 2 — who is this person?

The email on the request may be current OR historical.
Ghost copies of data often sit under an old address, so the agent
must collect every email, phone, and email-hash this user ever had.
"""

from __future__ import annotations

import csv
import re
from dataclasses import dataclass, field
from pathlib import Path

EMAIL_RE = re.compile(r"[A-Z0-9._%+\-]+@[A-Z0-9.\-]+\.[A-Z]{2,}", re.I)
USER_RE = re.compile(r"\buser_\d+\b", re.I)
HASH_RE = re.compile(r"\b[a-f0-9]{64}\b")


def normalize_email(value: str | None) -> str | None:
    if not value:
        return None
    email = value.strip().strip("\"'").lower()
    if not email or "@" not in email:
        return None
    return email


def normalize_phone(value: str | None) -> str | None:
    if not value:
        return None
    digits = re.sub(r"\D", "", value)
    return digits if len(digits) >= 8 else None


def normalize_hash(value: str | None) -> str | None:
    if not value:
        return None
    digest = value.strip().lower()
    return digest if HASH_RE.fullmatch(digest) else None


@dataclass
class ResolvedIdentity:
    """Everything we know about one human after identity resolution."""

    user_id: str
    name: str
    current_email: str
    emails: set[str] = field(default_factory=set)
    phones: set[str] = field(default_factory=set)
    hashes: set[str] = field(default_factory=set)
    matched_on: str = ""  # why we linked the request email to this user


class IdentityIndex:
    """In-memory phone book built from identities + audit history."""

    def __init__(self, dataset_dir: Path) -> None:
        self.by_user_id: dict[str, ResolvedIdentity] = {}
        self.email_to_user: dict[str, str] = {}
        self._load_current_identities(dataset_dir / "user_identities.csv")
        self._load_history(dataset_dir / "user_audit_log.csv")

    def _load_current_identities(self, path: Path) -> None:
        with path.open(newline="", encoding="utf-8") as handle:
            for row in csv.DictReader(handle):
                user_id = row["user_id"]
                person = ResolvedIdentity(
                    user_id=user_id,
                    name=row.get("name") or "",
                    current_email=row.get("email") or "",
                )
                email = normalize_email(person.current_email)
                if email:
                    person.emails.add(email)
                    self.email_to_user[email] = user_id
                phone = normalize_phone(row.get("phone"))
                if phone:
                    person.phones.add(phone)
                digest = normalize_hash(row.get("email_hash"))
                if digest:
                    person.hashes.add(digest)
                self.by_user_id[user_id] = person

    def _load_history(self, path: Path) -> None:
        with path.open(newline="", encoding="utf-8") as handle:
            for row in csv.DictReader(handle):
                person = self.by_user_id.get(row["user_id"])
                if person is None:
                    continue
                field_name = row.get("field_name") or ""
                for raw in (row.get("old_value"), row.get("new_value")):
                    if field_name == "email":
                        email = normalize_email(raw)
                        if email:
                            person.emails.add(email)
                            # Historical email still points at the same user_id.
                            self.email_to_user.setdefault(email, person.user_id)
                    elif field_name == "email_hash":
                        digest = normalize_hash(raw)
                        if digest:
                            person.hashes.add(digest)
                    elif field_name == "phone":
                        phone = normalize_phone(raw)
                        if phone:
                            person.phones.add(phone)

    def resolve(self, request_email: str) -> ResolvedIdentity | None:
        """Find the person for the email printed on the request."""
        email = normalize_email(request_email)
        if not email:
            return None
        user_id = self.email_to_user.get(email)
        if not user_id:
            return None
        person = self.by_user_id[user_id]
        matched_on = "current_email" if email == normalize_email(person.current_email) else "historical_email"
        # Return a copy so callers can stamp matched_on without mutating the index.
        return ResolvedIdentity(
            user_id=person.user_id,
            name=person.name,
            current_email=person.current_email,
            emails=set(person.emails),
            phones=set(person.phones),
            hashes=set(person.hashes),
            matched_on=matched_on,
        )
