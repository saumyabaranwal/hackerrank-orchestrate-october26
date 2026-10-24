# Ghost Data Still Exists — deletion-audit agent

Deterministic hybrid agent. It does **not** trust dashboards or deletion-worker
`SUCCESS`/`FAILED` flags. For every request it decides whether deletion was
asked for, who the person is (including old emails), what evidence still shows
at `audit_at`, what `deletion_rules.csv` requires, and then writes the official
step list.

No LLM is in the decision loop. There are no prompts to tune. Parsers are the
tools; the planner is a clerk over a rulebook.

## Setup

Python 3.10+ recommended. From the **repository root** (the folder that contains
`dataset/` and `code/`):

```text
python3 -m pip install -r code/requirements.txt
```

The only extra package is `pypdf` (PDF text). No API key. No `.env`.

Windows:

```text
python -m pip install -r code/requirements.txt
```

## Run (518 evaluation cases)

```text
python3 code/main.py
```

Writes `output.csv` at the repository root: one row per `dataset/deletion_requests.csv`
case, columns `case_id,deletion_status,steps_json`, sorted by numeric `case_id`.

```text
python3 code/main.py --run          # same as no args
python3 code/main.py --skeleton     # classifier + identity only
python3 code/main.py --evidence case_05
python3 code/main.py --plan case_05
python3 code/main.py --score-sample
python3 code/evaluation/main.py     # public sample + three team probes
```

`--evidence` is the filing cabinet (Brain 3). `--plan` is the full answer
(Brain 5), including accounts attached from *unique* activity when evidence
never printed the id.

## Architecture

```text
request row
    │
    ├─ Brain 1  classify     deletion?  else NOT_APPLICABLE []
    ├─ Brain 2  identity     current + historical email / phone / hash
    ├─ Brain 3  evidence     parse 94 files → observations; match this person at audit_at
    ├─ Brain 4  policy       deletion_rules.csv  DELETE | REDACT | ANONYMIZE | RETAIN
    └─ Brain 5  planner      COMPLETE = cited verifications only
                             INCOMPLETE = FINDING → REMEDIATION → VERIFICATION
```

`code/agent/pipeline.py` is the boss. It never invents policy.

### Tools (not LLM tools)

| Module | Job |
|---|---|
| `parsers.py` | SQL / JSON / log / txt / PDF → one Observation shape |
| `evidence.py` | Cabinet. Identity match on any file; **state** only from files captured ≤ `audit_at` |
| `identity.py` | Phone book from `user_identities.csv` + `user_audit_log.csv` |
| `planner.py` | One account per person; activity ids only if uniquely closer than every other request |

Images (`.png`) are not OCR’d. A screenshot *link* is not proof (contest Q&A).
PDFs are read with `pypdf`.

### Why no model in the loop

Extra steps are penalized. An LLM that guesses `account_5193` for the wrong
person is a real miss. Classification, policy, and step order are all
deterministic so a clean rerun produces the same `output.csv`.

Token usage for the 518-row run is zero. See `evaluation/usage_report.md`.

## Robustness rules baked in

- `reported_status` and activity `reported_result` are claims.
- Word-boundary ids (`user_21` must not match `user_210`).
- Replica ghost: if any copy at audit time is present, the record is present.
- Later exports may teach *who owns* an id; they may not rewrite at-audit PII.
- Global unique activity assignment over **sample + 518** so a sample DELETE
  is not given to a nearby eval case (and vice versa). Ties are skipped.
- Service aliases (`support_replica` → `support_platform`).

## Layout

```text
code/
  main.py
  requirements.txt
  README.md
  agent/           classify, identity, parsers, evidence, policy, planner, pipeline
  evaluation/
    main.py
    evaluation_report.md
    usage_report.md
```

Do not put API keys in this tree. Do not ship `dataset/` inside `code.zip`.
