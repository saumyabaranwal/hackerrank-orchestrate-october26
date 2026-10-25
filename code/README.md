# Ghost Data Still Exists: deletion-audit agent

A deterministic, evidence-first agent that audits whether a person's data was
really erased. It does **not** trust dashboards or the deletion worker's
`SUCCESS` / `FAILED` flags. For each request it decides:

1. Was deletion actually requested?
2. Who is this person (including old emails, phones and hashes)?
3. What evidence still shows at `audit_at`?
4. What does `deletion_rules.csv` require for each leftover?
5. What is the official ordered step list?

No LLM is in the decision loop, so there are no prompts to tune, no API keys,
no network calls, and a rerun produces the same `output.csv`.

**At a glance**

| | |
|---|---|
| Input | `dataset/deletion_requests.csv` (518 cases, `case_33`-`case_550`) |
| Output | `output.csv` at repo root: `case_id,deletion_status,steps_json` |
| Dependencies | Python stdlib + `pypdf` |
| Model / token cost | None / 0 tokens / $0 |
| Runtime | about 10 s with OCR cache; about 1 min if RapidOCR must re-read the 11 PNGs |
| Public sample | 32/32 status correct, 0 extra steps (see `evaluation/evaluation_report.md`) |

---

## 1. Quick start

Run everything from the **repository root** (the folder containing `dataset/`
and `code/`).

```text
# macOS / Linux
python3 -m pip install -r code/requirements.txt
python3 code/main.py

# Windows
python -m pip install -r code/requirements.txt
python code/main.py
```

Requirements: Python 3.10+. The only third-party package is `pypdf` (PDF text
extraction). No `.env`, no API key.

`code.zip` does **not** include `dataset/`. Put the unzipped tree in the
challenge repo as `code/`, so `dataset/` sits next to `code/`. The agent
auto-detects that layout. If you unzip somewhere else:

```text
python3 main.py --dataset /path/to/dataset --out /path/to/output.csv
```

`--dataset` is the folder that contains `deletion_requests.csv`. `--out` is the
output CSV path (default: repository root `output.csv`).

### Expected result

The run prints a one-line summary and writes `output.csv`:

```text
rows=518  COMPLETE=154  INCOMPLETE=354  NOT_APPLICABLE=10  obs=3245
```

If your numbers differ, see [Troubleshooting](#6-troubleshooting).

---

## 2. Commands

| Command | What it does |
|---|---|
| `python3 code/main.py` | Full run, writes `output.csv` (same as `--run`) |
| `python3 code/main.py --run` | Same as above |
| `python3 code/main.py --dataset PATH --out PATH` | Full run with explicit dataset and output paths |
| `python3 code/main.py --skeleton` | Classifier + identity only (no evidence/planning) |
| `python3 code/main.py --evidence case_05` | Show matched evidence for one case (Brain 3) |
| `python3 code/main.py --plan case_05` | Show the full step list for one case (Brain 5) |
| `python3 code/main.py --score-sample` | Score against the 32-case public sample |
| `python3 code/evaluation/main.py` | Public-sample scoring plus the three team test cases |

`--evidence` is the filing cabinet: what we can prove about this person.
`--plan` is the final answer, including accounts attached from *uniquely
closest* activity when evidence never printed the id.

### Verify a clean rerun

```text
rm -f output.csv
python3 code/main.py
sha256sum output.csv        # macOS: shasum -a 256 output.csv
python3 code/main.py
sha256sum output.csv        # hashes should be identical
```

Same input, same hash. There is no randomness, no model, and no network.

### Sanity checks on the output

- 518 rows, unique `case_id`, numeric order `case_33` ... `case_550`.
- `steps_json` parses as JSON on every row.
- `NOT_APPLICABLE` rows have `[]` (expected ids: `case_533`-`case_542`).
- `COMPLETE` rows contain only `VERIFICATION` steps, each with a non-empty `evidence_id`.
- `INCOMPLETE` rows run FINDING, then REMEDIATION, then VERIFICATION.

---

## 3. Architecture

```text
request row
    |
    +- Brain 1  classify   deletion requested?  else NOT_APPLICABLE []
    +- Brain 2  identity   current + historical email / phone / hash
    +- Brain 3  evidence   parse 94 files -> observations; match person at audit_at
    +- Brain 4  policy     deletion_rules.csv: DELETE | REDACT | ANONYMIZE | RETAIN
    +- Brain 5  planner    COMPLETE   = cited verifications only
                           INCOMPLETE = FINDING -> REMEDIATION -> VERIFICATION
```

`code/agent/pipeline.py` orchestrates the brains. It never invents policy.

| Module | Job |
|---|---|
| `classify.py` | Phrase-list classifier; non-deletion markers are checked first |
| `identity.py` | Identity index from `user_identities.csv` + `user_audit_log.csv` |
| `parsers.py` | SQL / JSON / log / txt / PDF to one common Observation shape |
| `evidence.py` | Evidence cabinet. Identity match on any file; **state** only from files captured at or before `audit_at` |
| `policy.py` | Reads `deletion_rules.csv` (CSV wins over built-in fallback) |
| `planner.py` | Builds the ordered step list; one profile per person; activity ids only if uniquely closer |
| `pipeline.py` | Wires the brains together |

### Output contract

Each `steps_json` item:

```json
{"step_no": 1, "phase": "FINDING", "system_id": "account_service",
 "resource_id": "account_005", "operation": "REPORT_REMAINING_RECORD",
 "state": "PRESENT", "evidence_id": "evidence_54"}
```

Order: phase (FINDING, REMEDIATION, VERIFICATION), then contest operation
order, then `system_id`, then `resource_id`.

---

## 4. Design rules (why it behaves this way)

- **Claims are not evidence.** `reported_status` and activity `reported_result` never set state.
- **Extra steps are worse than missing steps.** The planner prefers silence to guessing a neighbour's id.
- **Audit-time truth.** State comes only from files captured at or before `audit_at`. Later files may teach *who owns* an id, never rewrite at-audit PII.
- **Replica ghost.** If any copy at audit time is present, the record is present.
- **Exact ids.** Word-boundary matching, so `user_21` never matches `user_210`.
- **Unique activity assignment.** An activity id is attached only if this request is at least 10 minutes closer than every other request (sample + 518) and within 2 hours. Ties are skipped.
- **Catalog / screenshot window.** A `LINK_RESOURCE_IDENTITY` id or PNG leftover attaches only if the link time or screenshot `captured_at` falls inside `[requested_at, audit_at]`. Other evidence may still pre-date `requested_at` if it is the latest before `audit_at`.
- **Log `system=` vs `service=`.** `system=` is the store that holds the record. `service=` is the lookup component and is not `system_id`.
- **One live profile per person.** If two `USER_PROFILE` ids appear, keep the newest at audit.
- **Service aliases.** Replica hostnames map to official ids (`support_replica` to `support_platform`).
- **Fail closed.** Non-deletion gives `NOT_APPLICABLE` with `[]`. Unknown person would give `INCOMPLETE` with `[]`; that path fires **0 times** on the 518 (every request email resolves).

---

## 5. Known limitations

These are deliberate trade-offs, documented in `evaluation/evaluation_report.md`:

- The classifier is a phrase list. It is brittle on new wording by design.
- The 10-minute / 2-hour activity thresholds are tuned precision gates, not derived constants.
- Identifier-less 404s and null-field analytics rows in multi-user dumps are not attributed to anyone.
- The 11 `.png` consoles are OCR'd locally (RapidOCR). A screenshot *hyperlink* is still not proof; pixels of the record are.
- Identity lookup is email-first. A request with no email fails closed.
- Legal holds are wired (RETAIN to `VERIFY_RECORD_PRESENT`) but the public sample has none, so that path is untested on real data.

---

## 6. Troubleshooting

| Symptom | Fix |
|---|---|
| `ModuleNotFoundError: pypdf` | Run `python3 -m pip install -r code/requirements.txt` |
| `FileNotFoundError: dataset/...` | Run from the repository root, not from `code/`. Or pass `--dataset PATH` |
| Row counts differ from expected | Confirm the dataset is unmodified and complete (94 evidence files, 518 requests) |
| `output.csv` not found | It is written to the repository root, not `code/` |
| Old Python | Use Python 3.10 or newer |

---

## 7. Layout

```text
code/
  main.py
  requirements.txt
  README.md
  agent/        classify, identity, parsers, evidence, policy, planner, pipeline
  evaluation/
    main.py
    evaluation_report.md
    usage_report.md
```

Do not put API keys in this tree. Do not ship `dataset/` inside `code.zip`.
