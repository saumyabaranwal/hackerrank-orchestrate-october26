# Token usage report — full dataset run

This file describes the run that produced repository-root `output.csv`
(518 rows, `case_33`–`case_550`).

## Models

The deletion-audit agent is **deterministic**. The 518-row run called **no**
hosted or local language model and **no** vision model.

| Provider | Model name | Role |
|---|---|---|
| — | none | Classification, identity, evidence, policy, and planning are Python |

Parsers: Python stdlib (`csv`, `json`, `sqlite3`, `re`) plus `pypdf` for PDF
text. No OpenAI, Anthropic, Google, or local LLM endpoint.

## Call and token counts

| | Input tokens | Output tokens | Calls |
|---|---|---|---|
| Language models | 0 | 0 | 0 |
| Vision models | 0 | 0 | 0 |
| **Total** | **0** | **0** | **0** |

Requests in the run: **518**.

| | Total | Average per request |
|---|---|---|
| Input tokens | 0 | 0 |
| Output tokens | 0 | 0 |
| Combined tokens | 0 | 0 |
| Model calls | 0 | 0 |

## Cost

| | Total | Per request |
|---|---|---|
| Estimated USD | **$0.00** | **$0.00** |

No API keys were read. No `.env` is required.

## Runtime (non-token)

Evidence cabinet: 2891 observations from 94 files, loaded once per process
(batch + cache). Wall time for `python3 code/main.py --run` on the development
machine was about **3 seconds**.

If a vision model is added later for the 11 PNG consoles, it must only propose
observations whose **contents are shown** (not hyperlink ids). Those calls
would be recorded in a new row of this table. They are not part of the
submitted `output.csv` run.
