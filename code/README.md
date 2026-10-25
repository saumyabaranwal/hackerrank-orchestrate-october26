# Ghost Data Still Exists

## Deletion audit agent

This project audits whether a customer's data was actually deleted. It uses participant-provided identity, policy, activity, and evidence files. It does not treat a workflow status such as `SUCCESS` or `COMPLETE` as proof.

For each request, the pipeline:

1. Checks whether the request authorizes deletion.
2. Resolves the person from current and historical identifiers.
3. Finds evidence available by the case's `audit_at` cutoff.
4. Applies the action in `deletion_rules.csv`.
5. Writes the required findings, remediation, and verification steps.

The solution is deterministic Python. It makes no hosted model calls and requires no API keys. RapidOCR reads screenshot text locally; parsed text is cached.

## At a glance

| Item | Details |
|---|---|
| Input | `dataset/deletion_requests.csv` — 518 requests, `case_33` through `case_550` |
| Output | Repository-root `output.csv` with `case_id,deletion_status,steps_json` |
| Runtime dependencies | Python 3.10+, `pypdf>=4.0.0`, `rapidocr-onnxruntime==1.2.3` |
| Hosted model usage | None; 0 tokens; $0 estimated cost |
| Typical runtime | About 10 seconds with OCR cache; about 1 minute for a cold OCR run |
| Public sample | 32/32 status matches; 18/32 exact step structures; 0 extra steps |
| Full dataset run | 154 COMPLETE, 354 INCOMPLETE, 10 NOT_APPLICABLE; 3,245 observations |

## 1. Run the solution

Run commands from the repository root—the directory containing `dataset/` and `code/`.

```bash
# macOS / Linux
python3 -m pip install -r code/requirements.txt
python3 code/main.py

# Windows
python -m pip install -r code/requirements.txt
python code/main.py
```

The run writes `output.csv` to the repository root. Expected summary:

```text
rows=518  COMPLETE=154  INCOMPLETE=354  NOT_APPLICABLE=10  obs=3245
```

To select input and output paths explicitly:

```bash
python3 code/main.py --dataset /path/to/dataset --out /path/to/output.csv
```

`--dataset` must point to the directory containing `deletion_requests.csv`. `code.zip` should contain the code tree, not the challenge dataset.

## 2. Useful commands

| Command | Purpose |
|---|---|
| `python3 code/main.py` | Run the full pipeline |
| `python3 code/main.py --run` | Same as the full run |
| `python3 code/main.py --skeleton` | Classify requests and resolve identities without evidence planning |
| `python3 code/main.py --evidence case_05` | Show evidence matched to a case |
| `python3 code/main.py --plan case_05` | Show the planned steps for a case |
| `python3 code/main.py --score-sample` | Compare predictions with the 32-case public sample |
| `python3 code/evaluation/main.py` | Run public-sample scoring and team checks TC1–TC6 |

### Check deterministic output

```bash
python3 code/main.py
sha256sum output.csv       # macOS / Linux
python3 code/main.py
sha256sum output.csv
```

The hashes should match when the input data and OCR cache are unchanged. On Windows, use `Get-FileHash output.csv -Algorithm SHA256` between runs.

### Output checks

- There are 518 unique rows, in the same order as `deletion_requests.csv`.
- Every `steps_json` value is valid JSON.
- `NOT_APPLICABLE` cases use `[]`; in this dataset those are `case_533` through `case_542`.
- `COMPLETE` rows contain only evidence-cited verification steps.
- `INCOMPLETE` rows contain findings, then proposed remediation, then future verification.
- The current output has no empty `COMPLETE` plans.

## 3. How the pipeline works

```text
Request
  ├─ Classification: deletion request or NOT_APPLICABLE
  ├─ Identity: current and historical email, phone, and hash
  ├─ Evidence: parse files and select facts available by audit_at
  ├─ Policy: apply deletion_rules.csv
  └─ Planning: order findings, remediation, and verification
```

| Module | Responsibility |
|---|---|
| `classify.py` | Phrase-based request classification; non-deletion markers are checked first |
| `identity.py` | Builds the identity index from current and historical records |
| `parsers.py` | Extracts observations from SQL, JSON, logs, text, PDFs, and PNG screenshots |
| `evidence.py` | Matches evidence to people and enforces the `audit_at` cutoff for state |
| `policy.py` | Loads required actions from `deletion_rules.csv` |
| `planner.py` | Creates and orders the final steps |
| `pipeline.py` | Connects the stages and writes the output |

Every step has `step_no`, `phase`, `system_id`, `resource_id`, `operation`, `state`, and `evidence_id`. Steps sort by phase, the problem statement's operation order, `system_id`, then `resource_id`.

## 4. Decision rules

- Workflow statuses and activity results are claims; evidence establishes record state.
- State is based on files captured at or before `audit_at`. Later files may help identify ownership but cannot change the at-cutoff state.
- If any replica is present at the cutoff, the record is treated as present.
- Identifier matching uses exact or word-boundary matches (`user_21` does not match `user_210`).
- An activity event is assigned only when it is within two hours of a request and at least ten minutes closer to that request than to any competing request. Ambiguous events are skipped.
- Catalog links and screenshot findings attach only within the inclusive `[requested_at, audit_at]` window. Ordinary evidence may predate the request if it is the latest eligible snapshot before the audit cutoff.
- A log's `system=` field identifies the data store. `service=` identifies a lookup component.
- The planner keeps one `USER_PROFILE` per person, selecting the newest eligible profile.
- A catalog link without a corresponding evidence file establishes ownership, not record state. The solution does not invent PRESENT or ABSENT for `export_1842`.
- Archive presence alone does not establish whether restore access is allowed or blocked. Cases 39 and 55 are excluded from scoring by the organizers; the output avoids making unsupported restore claims for them.

### PII uncertainty

The planner now represents PII state as true, false, or unknown and avoids a redaction/anonymization verification when the state is unknown. The parser still infers “no recognized PII fields” as false in some formats. That means parser-level uncertainty is not fully preserved for every record shape; see the evaluation report's limitations.

## 5. Known limitations

- Request classification uses phrase lists and may miss unfamiliar wording. It fails closed to `NOT_APPLICABLE`.
- Activity matching thresholds are precision gates tuned against the public sample, not derived constants.
- Identifier-less 404s and null-identifier rows in multi-user dumps are not attributed to a person.
- A person with two genuinely live profiles may be reduced to one profile by the current single-profile assumption.
- Legal-hold handling is implemented as `RETAIN` plus `VERIFY_RECORD_PRESENT`, but no public sample exercises it.
- A parser that fails to read a relevant record could cause the solution to miss that record.

See `evaluation/evaluation_report.md` for measured public-sample results and documented gaps. See `evaluation/usage_report.md` for runtime, OCR, token, and cost details.

## 6. Troubleshooting

| Symptom | What to check |
|---|---|
| `ModuleNotFoundError: pypdf` | Install `code/requirements.txt` from the repository root |
| `ModuleNotFoundError: rapidocr_onnxruntime` | Install requirements; the documented version is `1.2.3` |
| Dataset file not found | Run from the repository root or pass `--dataset PATH` |
| Output row count differs | Check that the dataset has 518 requests and 94 evidence files |
| Summary says `obs=3243` | Check that `pypdf` installed correctly; the four PDFs should contribute parsed observations |
| Output file not found | The default output is repository-root `output.csv` |
| Windows archive contains an extra `code/` directory | Zip the contents of `code/`, not the `code/` directory itself |

## 7. Package layout

```text
code/
  main.py
  requirements.txt
  README.md
  agent/        classification, identity, parsers, evidence, policy, planner, pipeline
  evaluation/
    main.py
    evaluation_report.md
    usage_report.md
```

Include `agent/png_ocr_cache.json` in the code package so the evaluator can use cached screenshot text. Exclude `__pycache__` and do not include the dataset or secrets.
