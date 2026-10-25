# Token usage report: full dataset run

This report covers the run that produced repository-root `output.csv`
(518 rows, `case_33`–`case_550`, COMPLETE=154, INCOMPLETE=354,
NOT_APPLICABLE=10, observations=3245).

Gemini is used **only** to classify `request_text` (Brain 1). The planner does
not call the model. `agent/llm_cache.json` is in the zip, so a judge rerun
does not need `GEMINI_API_KEY` and does not change `output.csv`.

## Summary

| | |
|---|---|
| Language-model calls (cache fill) | **387** unique classify prompts (Gemini 3.5 Flash-Lite) |
| Language-model calls (judge rerun with cache) | **0** live |
| Hosted vision-model calls | **0** |
| Local OCR | RapidOCR ONNX on 11 PNG consoles (`agent/png_ocr_cache.json`) |
| Total tokens (input + output), cache fill | **≈ 42,000 in + 390 out** |
| Estimated cost | **< $0.01** (Flash-Lite list price; this volume is rounding error) |
| Network calls during a cached rerun | None |
| API keys in the zip | **None** |

The planner is still deterministic Python. No LLM writes `steps_json`. RapidOCR
is perception. Gemini is intake classification with a non-deletion veto.

## Models

| Provider | Model | Role |
|---|---|---|
| Google | `gemini-3.5-flash-lite` | Brain 1: deletion vs not (`YES`/`NO`) |
| none (local ONNX) | RapidOCR (`rapidocr-onnxruntime==1.2.3`) | 11 PNG consoles → observation text |

Libraries: Python stdlib plus `pypdf>=4.0.0`, `rapidocr-onnxruntime==1.2.3`,
`google-genai>=1.0.0`.

## Calls and tokens (cache fill that produced `llm_cache.json`)

| | Input tokens | Output tokens | Calls |
|---|---|---|---|
| Gemini 3.5 Flash-Lite | ≈ 42,000 | ≈ 390 | 387 |
| Hosted vision | 0 | 0 | 0 |
| **Total** | **≈ 42,000** | **≈ 390** | **387** |

Requests in the scored run: **518** (plus 32 sample texts; unique prompts 398,
of which 10 N/A texts never leave the veto and 387 were sent to Gemini).

| | Total | Per request (518) |
|---|---|---|
| Input tokens | ≈ 42,000 | ≈ 81 |
| Output tokens | ≈ 390 | ≈ 0.8 |
| Combined tokens | ≈ 42,400 | ≈ 82 |
| Live model calls (fill) | 387 | 0.75 |
| Live model calls (cached rerun) | 0 | 0 |
| Estimated USD | < $0.01 | < $0.00002 |

## Runtime (non-token)

| | |
|---|---|
| Evidence files parsed | 94 (28 JSON, 26 log, 24 SQL, 11 PNG, 4 PDF, 1 txt) |
| Observations extracted | **3245** |
| Screenshot OCR | RapidOCR, cache `agent/png_ocr_cache.json` |
| LLM classify | Gemini, cache `agent/llm_cache.json` |
| Wall time, cached `python3 code/main.py --run` | about **10 s** |

## How to verify

1. **Planner has no LLM import:**

   ```text
   grep -n llm code/agent/planner.py
   ```

   Expect no matches.

2. **Key is not in the zip:**

   ```text
   grep -R "GEMINI_API_KEY\|AIza\|AQ\." code/agent --include='*.json' --include='*.py'
   ```

   Expect no secrets. `llm_client.py` only *reads* the env var.

3. **Offline cached rerun:** unset `GEMINI_API_KEY` and run `python3 code/main.py`.
   Status mix stays 154 / 354 / 10.

## Guardrails (why this is not an LLM planner)

- Non-deletion phrase markers always win. Gemini cannot authorize erasure on
  an invoice / download / “I am not asking for deletion.”
- A deletion-verb phrase still authorizes if Gemini says NO or the API is down
  (sample `case_25` would otherwise have flipped to N/A).
- Gemini never emits a `resource_id` or a `steps_json` item.
