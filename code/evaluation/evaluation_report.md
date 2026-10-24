# Evaluation report — Ghost Data Still Exists

Public sample: `dataset/sample_deletion_requests.csv` vs `dataset/sample_output.csv` (32 cases).  
Hidden eval: 518 rows in root `output.csv` (`case_33`–`case_550`).  
Runner: `python3 code/evaluation/main.py`.

We do **not** use organizer-only truth. Extra steps are treated as harmful (contest Q&A).

## 1. Case-level status accuracy

| Split | Metric | Result |
|---|---|---|
| Public sample (32) | `deletion_status` exact | **32 / 32 (100%)** |
| Public sample | COMPLETE / INCOMPLETE / N/A mix | 10 COMPLETE, 22 INCOMPLETE, 0 N/A (matches gold) |
| Full run (518) | Produced rows | 518, numeric `case_id` order |
| Full run | Status mix | 163 COMPLETE, 345 INCOMPLETE, 10 NOT_APPLICABLE |
| Full run | N/A ids | `case_533`–`case_542` only |

Status is the required decision. The remaining sample gaps are **missing resource ids**, not flipped COMPLETE/INCOMPLETE.

## 2. Step-level and field-level accuracy

Compared as ordered `steps_json` arrays on the 32 sample cases.

| Metric | Result |
|---|---|
| Exact structure (phase, operation, system, resource, state) | **18 / 32** |
| Predicted steps | 174 |
| Gold steps | 193 |
| Extra predicted steps (precision errors) | **0** |
| Missing gold steps (recall errors) | **19** |
| Field match on aligned prefix (phase) | 174 / 174 |
| Field match on aligned prefix (operation, state) | 148 / 174 |
| Field match on aligned prefix (system_id, resource_id) | 142 / 174 |

Interpretation: when we emit a step, we do not emit a *neighbour’s* leftover. We under-report identifier-less 404s and anonymized analytics that never carry this person’s email/`user_id`. That is the intended trade given extra-step penalties.

COMPLETE rows only contain `VERIFICATION` with a non-empty `evidence_id`.  
INCOMPLETE rows are FINDING → REMEDIATION → VERIFICATION; future work uses empty `evidence_id`.  
N/A rows are `[]`.

## 3. Sequence accuracy

Within each predicted list:

- Phase order is always FINDING, then REMEDIATION, then VERIFICATION.
- Operations follow the contest table, then `system_id`, then `resource_id`.
- On the 18 exact-match cases, sequence matches gold 18 / 18.
- On the 14 partial cases, sequence of *emitted* steps still obeys the table; gold differs because missing resources would have slotted in by `resource_id` sort.

## 4. Three additional evaluation cases (team)

Runnable in `evaluation/main.py`. All three **PASS** on the current agent.

### TC1 — Non-deletion must not authorize erasure

**Why:** Hidden eval includes non-deletion intake. A “complete the ticket” email is not a delete.

**Probe:** four synthetic texts (invoices, phone correction, download, stop marketing / leave account).

**Expect:** classifier `is_deletion_request` is false → planner would emit `NOT_APPLICABLE` + `[]`.

**Result:** PASS.

### TC2 — Historical identity

**Why:** Ghost copies live under old addresses. Case_30 requests as `camille.bernard86@outlook.com`.

**Probe:** resolve that email against `user_identities.csv` + `user_audit_log.csv`.

**Expect:** `user_30`, `matched_on=historical_email`, identity set also contains `camille.bernard@outlook.com`.

**Result:** PASS.

### TC3 — Do not steal a neighbour’s account

**Why:** Extra steps are penalized. Closest-DELETE on a busy morning assigned `account_5193` to the wrong person and kept a stale `account_6523`.

**Probe:** plan `case_17` and `case_18`; forbid those two resource ids.

**Expect:** neither id appears in `steps_json`.

**Result:** PASS.

## 5. Failures found and improvements made

| Failure | What we saw | Fix |
|---|---|---|
| Classifier misses | Early word list missed “deleting”, “left behind”, Spanish/French delete verbs | Broader marker list; **non-deletion markers checked first** |
| `user_21` ⊂ `user_210` | Substring match linked the wrong human | Word-boundary / exact `user_id` |
| Replica ghost | Primary 404, failover still PRESENT | Any present copy at audit time → present |
| `support_replica` as system_id | Grader wants `support_platform` | `SERVICE_ALIASES` |
| Old evidence preferred | Cited `evidence_02` over later `evidence_92` | Latest file time at or before `audit_at` |
| Future snapshot leak | Sep 17 bundle stamped inner Sep 15 made support look already redacted | **File** capture time for state; later files may only teach ownership |
| Extra accounts | 15-minute closest DELETE picked the neighbour | Removed. **Global unique assignment**: attach only if this request is ≥10 minutes closer than every other request in sample+518, within 2 hours. Ties skipped |
| Two accounts for one email | Historical 404 `account_6523` plus later `account_4092` | Keep **one** USER_PROFILE, the newest at audit |
| Support PII | Latest-after-audit snapshot `pii=false` hid `REPORT_EXPOSED_PII` | At-audit export wins |

### Known remaining failures (not “fixed” on purpose)

- Identifier-less 404s and null analytics in multi-user dumps (sample misses ~14 cases’ extra resources).
- `account_004` and two gold `audit_record_*` ids do not appear in participant evidence or activity.
- 11 PNG consoles are not OCR’d. A screenshot *link* is not treated as proof (official Q&A).
- Legal holds are wired as RETAIN → `VERIFY_RECORD_PRESENT` but the public sample has none.

Chasing 32/32 exact structure by inventing ids would overfit the sample and add extras on the hidden 518.

## 6. Full-dataset sanity (the run that wrote `output.csv`)

```text
python3 code/main.py --run
# rows=518  COMPLETE=163  INCOMPLETE=345  NOT_APPLICABLE=10  obs=2891
```

Checks after write: 518 unique ids `case_33`–`case_550`, numeric sort, JSON-parseable `steps_json`, N/A arrays empty, COMPLETE steps all `VERIFICATION` with `evidence_id`.
