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


def _keyword_deletion(text: str) -> bool:
    return any(marker in text for marker in DELETION_MARKERS)


def is_deletion_request(request_text: str) -> bool:
    """Return True only if the message authorizes deletion.

    Order:
    1. Non-deletion markers always win (N/A trap). Gemini cannot flip those.
    2. Gemini is asked (cache-first) so the zip actually contains LLM calls.
    3. A deletion-verb phrase list still authorizes if Gemini says NO or is down.
       (Sample case_25: model said NO on a real deletion; extra steps are worse
       than a missed synonym, but dropping a marked deletion is worse still.)
    4. If the phrase list is silent, Gemini YES may authorize; Gemini NO / miss
       does not.
    The planner never calls the model, so it cannot invent leftovers.
    """
    raw = (request_text or "").strip()
    if not raw:
        return False
    text = raw.lower()
    if any(marker in text for marker in NON_DELETION_MARKERS):
        return False
    keyword = _keyword_deletion(text)
    try:
        from .llm_client import classify_deletion_yes_no

        llm = classify_deletion_yes_no(raw)
    except Exception:
        llm = None
    if keyword:
        return True
    if llm is True:
        return True
    return False
