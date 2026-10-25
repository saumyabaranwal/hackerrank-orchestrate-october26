# Ghost Data Still Exists: deletion-audit agent

A deterministic, evidence-first agent that audits whether a person's data was
really erased. It does **not** trust dashboards or the deletion worker's
`SUCCESS` / `FAILED` flags. For each request it decides:

1. Was deletion actually requested?
2. Who is this person (including old emails, phones and hashes)?
3. What evidence still shows at `audit_at`?
4. What does `deletion_rules.csv` require for each leftover?
5. What is the official ordered step list?

Gemini classifies intake text (Brain 1) with a **non-deletion veto** so an N/A
cannot become a deletion. The planner still does **not** call the model, so it
cannot invent leftovers. Screenshot consoles are RapidOCR (cached). Answers
for Gemini live in `agent/llm_cache.json`, so a judge rerun matches `output.csv`
without a key.

**At a glance**

| | |
|---|---|
| Input | `dataset/deletion_requests.csv` (518 cases, `case_33`–`case_550`) |
| Output | `output.csv` at repo root: `case_id,deletion_status,steps_json` |
| Dependencies | Python stdlib + `pypdf` + `rapidocr-onnxruntime==1.2.3` + `google-genai` |
| Model | Gemini 3.5 Flash-Lite for intake classify only; RapidOCR for 11 PNGs |
| Token cost (this run) | classify cache fill ≈ 42k in / 0.4k out, **< $0.01**; judge rerun **0** live calls |
| Runtime | about 10 s with OCR + LLM caches |
| Public sample | **32/32** status, **18/32** exact structure, **0** extra steps |
| Full run | **154** COMPLETE, **354** INCOMPLETE, **10** NOT_APPLICABLE, **3245** observations |

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

Requirements: Python 3.10+. Third-party: `pypdf`, `rapidocr-onnxruntime==1.2.3`,
`google-genai`. **No API key is required** for a judge rerun: `agent/llm_cache.json`
and `agent/png_ocr_cache.json` are in the zip. Optional:

```text
export GEMINI_API_KEY=...   # only needed to refresh the classify cache
```

Never put the key in `code.zip`.

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

If your numbers differ, see [Troubleshooting](#6-troubleshooting). A cold OCR
pass (cache miss) can take about a minute; the observation count should still
be 3245.

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
| `python3 code/evaluation/main.py` | Public-sample scoring plus team tests **TC1–TC7** |

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

Same input, same hash. With `llm_cache.json` and `png_ocr_cache.json` in the zip there is no live Gemini call and no OCR re-run; the planner is deterministic Python.

### Sanity checks on the output

- 518 rows, unique `case_id`, same order as `deletion_requests.csv`
  (`case_33` … `case_550`).
- `steps_json` parses as JSON on every row.
- `NOT_APPLICABLE` rows have `[]` (expected ids: `case_533`–`case_542`).
- `COMPLETE` rows contain only `VERIFICATION` steps, each with a non-empty `evidence_id`.
- `INCOMPLETE` rows run FINDING, then REMEDIATION, then VERIFICATION.
- Empty COMPLETE: **none**. `export_1842` is not invented. Dual-system rows: **0**.

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
| `classify.py` | Non-deletion veto, then Gemini (cached), then deletion-verb fallback |
| `llm_client.py` | Gemini 3.5 Flash-Lite; cache `llm_cache.json`; no key → phrase list |
| `identity.py` | Identity index from `user_identities.csv` + `user_audit_log.csv` |
| `parsers.py` | SQL / JSON / log / txt / PDF / **PNG (RapidOCR + cache)** → Observation |
| `evidence.py` | Evidence cabinet. Identity match on any file; **state** only from files captured at or before `audit_at` |
| `policy.py` | Reads `deletion_rules.csv` (CSV wins over built-in fallback) |
| `planner.py` | Ordered step list; one profile per person; unique activity; catalog/PNG **window**; unknown PII/restore stay unknown |
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
- **Catalog / screenshot window.** A `LINK_RESOURCE_IDENTITY` id or PNG leftover attaches only if the link time or screenshot `captured_at` falls inside `[requested_at, audit_at]`. Ordinary SQL/JSON/logs may still pre-date `requested_at` if they are the latest before `audit_at`.
- **Log `system=` vs `service=`.** `system=` is the store that holds the record. `service=` is the lookup component and is not `system_id`.
- **One live profile per person.** If two `USER_PROFILE` ids appear, keep the newest at audit.
- **Unknown ≠ false.** Missing `pii_exposed` / `enabled` / `restore_allowed` stay `None`. The planner does **not** emit `VERIFY_RECORD_REDACTED`, `VERIFY_DATA_FLOW_DISABLED`, or restore ops from an unknown flag.
- **Archive presence ≠ restore permission.** A backup listed on a console (`evidence_32`) is not proof restore is allowed or blocked.
- **LINK without a file is ownership, not state.** `export_1842` has a catalog link and zero evidence files — we do not invent PRESENT/ABSENT.
- **Screenshot pixels vs hyperlink.** Official Q&A: a hyperlink in a shot is not a leftover. Pixels of the record itself are evidence (these 11 PNGs).
- **Service aliases.** Replica hostnames map to official ids (`support_replica` → `support_platform`).
- **Fail closed.** Non-deletion gives `NOT_APPLICABLE` with `[]`. Unknown person would give `INCOMPLETE` with `[]`; that path fires **0** times on the 518 (every request email resolves).

---

## 5. Known limitations

These are deliberate trade-offs, documented in `evaluation/evaluation_report.md`:

- The classifier is a phrase list. It is brittle on new wording by design.
- The 10-minute / 2-hour activity thresholds are tuned precision gates, not derived constants.
- Identifier-less 404s and null-field analytics rows in multi-user dumps are not attributed to anyone.
- PNG OCR only attaches **catalog-linked** resource ids off the screen; side-panel hyperlinks are ignored.
- Identity lookup is email-first. A request with no email fails closed.
- Legal holds are wired (RETAIN → `VERIFY_RECORD_PRESENT`) but the public sample has none, so that path is untested on real data.
- Organizers exclude `case_39` and `case_55` from scoring. We still emit honest plans (no fabricated restore/flow permission).

---

## 6. Troubleshooting

| Symptom | Fix |
|---|---|
| `ModuleNotFoundError: pypdf` | Run `python3 -m pip install -r code/requirements.txt` |
| `ModuleNotFoundError: rapidocr_onnxruntime` | Same install. Pin is `==1.2.3` (1.4.x is not used) |
| `ModuleNotFoundError: google.genai` | Same install. Not needed if `llm_cache.json` is present |
| `FileNotFoundError: dataset/...` | Run from the repository root, not from `code/`. Or pass `--dataset PATH` |
| Row counts differ from expected | Confirm the dataset is unmodified (94 evidence files, 518 requests) and OCR cache is present (`code/agent/png_ocr_cache.json`) |
| Observation count 3243 not 3245 | `pypdf` failed to import; PDF files produced 0 rows. Reinstall requirements |
| `output.csv` not found | It is written to the repository root, not `code/` |
| Old Python | Use Python 3.10 or newer |
| Windows zip has an extra `code\` folder | Zip the *contents* of `code/`, not the folder itself. Exclude `__pycache__` |

---

## 7. Layout

```text
code/
  main.py
  requirements.txt
  README.md
  agent/        classify, llm_client, identity, parsers, evidence, policy, planner, pipeline
                png_ocr_cache.json   (RapidOCR text for 11 consoles)
                llm_cache.json       (Gemini YES/NO for intake; no API key inside)
  evaluation/
    main.py                 public sample + TC1–TC7
    evaluation_report.md
    usage_report.md
```

Do not put API keys in this tree. Do not ship `dataset/` inside `code.zip`.
Do not ship `__pycache__`. Include `agent/png_ocr_cache.json` so judges do not
need a GPU or a cold OCR pass.
