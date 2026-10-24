"""Brain 1 — is this actually a deletion request?

The agent must not delete anyone who asked for something else
(fix my phone number, download my data, stop marketing emails).

Those cases are NOT_APPLICABLE with empty steps.
"""

from __future__ import annotations

# Phrases that mean "please erase me" across the languages in this dataset.
DELETION_MARKERS = [
    # English
    "delete",
    "deleting",
    "deleted",
    "deletes",
    "deletion",
    "erase",
    "erased",
    "erasure",
    "close my account",
    "close this account",
    "closed",
    "permanently deleted",
    "account-deletion",
    "remove my account",
    "remove my profile",
    "remove the profile",
    "remove records",
    "remove any remaining",
    "remove that search",
    "left behind",
    "already been removed",
    "inspect the actual systems",
    "finish the deletion",
    "complete the deletion",
    "disconnected my account",
    "would like it closed",
    "confirm that the profile is gone",
    "confirm that the account was fully removed",
    "verify that my account was deleted",
    "internal deleted-account",
    "audit the deletion",
    # French / Spanish / Portuguese
    "suppression",
    "supprimer",
    "eliminar",
    "eliminación",
    "exclusão",
    "excluir",
    # Korean / Japanese
    "삭제",
    "削除",
]

# If these appear, the person is NOT asking for deletion.
# Check these first so "I am not asking for deletion" does not get flipped.
NON_DELETION_MARKERS = [
    "i am not asking for deletion",
    "not a request to erase",
    "not asking for deletion",
    "do not close the account",
    "don't delete",
    "please don't delete",
    "leave the account active",
    "keep the account as it is",
    "leave my profile",
    "continue using the service",
    "without removing any of my records",
    "marketing lists only",
    "stop the promotional emails",
    "information request",
    "download my account information",
    "copy of last year's invoices",
    "copy of the information held",
    "change the email address used for this account",
    "mobile number on my profile is out of date",
    "surname is misspelled",
    "help resetting the login",
]


def is_deletion_request(request_text: str) -> bool:
    """Return True only if the message authorizes deletion."""
    text = (request_text or "").strip().lower()
    if not text:
        return False
    if any(marker in text for marker in NON_DELETION_MARKERS):
        return False
    return any(marker in text for marker in DELETION_MARKERS)
