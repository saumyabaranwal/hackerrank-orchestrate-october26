# Ghost Data Audit Agent

My solution to **HackerRank Orchestrate, October 2026 ("Ghost Data Still Exists")**.

A deletion workflow can report *Complete* while the user's data still lives on in databases, logs, exports, search indexes, or screenshots. This agent audits each deletion request, decides whether deletion actually happened, and outputs the ordered steps needed to finish it safely.

> The original challenge brief is in [`problem_statement.md`](problem_statement.md). The agent's code is in [`code/`](code/).

## What it does

For each of the 518 requests, the agent:

1. **Decides if deletion was requested at all.** Non-deletion requests become `NOT_APPLICABLE` with no steps.
2. **Works out who the person is**, including current and historical identities such as old emails.
3. **Finds what still exists** at the audit time across JSON, nested logs, PDFs, SQL snapshots, and screenshots (OCR). Reported workflow statuses are treated as claims, not proof.
4. **Applies the deletion rules** for each data category.
5. **Plans the steps** as findings, then remediation, then verification, in the required order, citing evidence IDs.

Output is `output.csv` with `case_id, deletion_status, steps_json`.

## Architecture: five stages

| Stage | Job | How |
|---|---|---|
| 1. Classify | Was deletion requested? | Phrase matcher, plus bounded Gemini classification. Non-deletion markers always win. |
| 2. Identity | Who is this person? | Email-first resolution across the identity table and audit log. |
| 3. Evidence | What exists at `audit_at`? | Parsers for JSON, logs, PDFs (`pypdf`), and screenshots (RapidOCR). |
| 4. Policy | What does the rule require? | Reads `deletion_rules.csv`. |
| 5. Planner | What steps, in what order? | Deterministic. No LLM writes steps. |

The LLM is used **only** in stage 1. The planner is deterministic on purpose, so the agent can't invent resource IDs or steps. Gemini results are cached in `llm_cache.json`, so reruns are free and reproducible. API keys are read from the `GEMINI_API_KEY` environment variable and never stored in the repo.

## Design decisions

- **Precision over guessing.** Extra steps are penalized, so the agent never guesses the "closest" resource to delete. An activity ID attaches to a request only if one request is clearly the best match (at least 10 minutes closer than any other, within a 2-hour window).
- **Unknown is not false.** PII state is three-valued (present, absent, unknown). Missing fields never become "clean," and restore steps are only emitted when the restore policy is actually known.
- **Time-window gating.** Screenshot and catalog evidence only counts when its timestamp falls inside the request window.
- **Claims vs. proof.** Workflow statuses and operation results are never treated as evidence of the real state.

## Results

| Run | Result |
|---|---|
| Full run | 518 / 518 rows: 154 `COMPLETE`, 354 `INCOMPLETE`, 10 `NOT_APPLICABLE` |
| 32-case sample | Correct status on **32 / 32** |
| 32-case sample, steps | **174 / 193** expected steps recovered, **0 extra steps** |
| Custom test cases | TC1–TC7 pass (ordering, cutoff, restore-unknown, PII-unknown, and more) |

Token usage for a cached rerun: 0 live model calls. See `code/evaluation/usage_report.md`.

## Known limitations

- Only **18 / 32** sample rows match the reference exactly. The gap is leftovers with no identifier (some 404s and analytics rows) and a few IDs that appear only in the reference answers. Recovering them would mean guessing and risking extra steps, so I left them out on purpose.
- Stage 1 relies partly on a phrase list, which is brittle to unusual wording.
- Screenshot reading depends on pinned OCR (`rapidocr-onnxruntime==1.2.3`) and a committed OCR cache.

## Run it

Setup and run instructions are in [`code/README.md`](code/README.md). From the repo root:

```bash
pip install -r code/requirements.txt
python3 code/main.py --run          # writes output.csv for all 518 requests
python3 code/evaluation/main.py     # sample score + custom test cases
```

Evaluation write-ups: [`code/evaluation/evaluation_report.md`](code/evaluation/evaluation_report.md) and [`code/evaluation/usage_report.md`](code/evaluation/usage_report.md).

## About

Built by **Saumya Baranwal** (B.Tech CSE, JIIT Noida) during the 24-hour HackerRank Orchestrate challenge, using an AI coding agent. The full build conversation is in [`log.txt`](log.txt).
