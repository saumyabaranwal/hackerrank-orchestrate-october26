# Token usage report: full dataset run

This report covers the run that produced repository-root `output.csv`
(518 rows, `case_33`-`case_550`).

## Summary

| | |
|---|---|
| Language-model calls | **0** |
| Hosted vision-model calls | **0** |
| Local OCR | RapidOCR ONNX on 11 PNG consoles (cached in `agent/png_ocr_cache.json`) |
| Total tokens (input + output) | **0** |
| Estimated cost | **$0.00** |
| Network calls during the run | None |
| API keys read | None |

## Models

The planner is **deterministic**. Classification, identity, evidence matching
and policy are Python. Screenshot text is local RapidOCR (`rapidocr-onnxruntime==1.2.3`),
not a hosted VLM. No LLM writes `steps_json`.

| Provider | Model | Role |
|---|---|---|
| none (local ONNX) | RapidOCR | 11 PNG consoles → observation text |
| none | none | no LLM |

Libraries: Python stdlib plus `pypdf` and `rapidocr-onnxruntime==1.2.3`.
No OpenAI, Anthropic, Google or local LLM endpoint.

## Calls and tokens

| | Input tokens | Output tokens | Calls |
|---|---|---|---|
| Language models | 0 | 0 | 0 |
| Vision models | 0 | 0 | 0 |
| **Total** | **0** | **0** | **0** |

Requests in the run: **518**

| | Total | Per request |
|---|---|---|
| Input tokens | 0 | 0 |
| Output tokens | 0 | 0 |
| Combined tokens | 0 | 0 |
| Model calls | 0 | 0 |
| Estimated USD | $0.00 | $0.00 |

## Runtime (non-token)

| | |
|---|---|
| Evidence files parsed | 94 |
| Observations extracted | 3244 |
| Screenshot OCR | RapidOCR (local ONNX), 11 PNG consoles, **0** cloud tokens |
| Loading strategy | Parsed once per process, then cached (batch + cache) |
| Wall time, `python3 code/main.py --run` | about 3 seconds on the development machine |

Timing is approximate and hardware-dependent. Measure it yourself with:

```text
time python3 code/main.py --run
```

## How to verify the zero-usage claim

1. **No model SDKs or HTTP clients in the code path:**

   ```text
   grep -rEi "openai|anthropic|google.generativeai|httpx" code/agent code/main.py
   ```

   Expect no SDK imports. Do not grep the word `requests`; it matches `inspect_requests`.

2. **Dependencies:** `code/requirements.txt` lists only `pypdf`.

3. **No credentials:** no `.env`, no environment variable is read.

4. **Offline run:** disconnect from the network and run `python3 code/main.py`. The output is unchanged.

## If a vision model is added later

A vision model was considered for the 11 PNG console screenshots but is **not**
part of the submitted run. If added, it must:

- only **propose** observations whose contents are actually shown (a hyperlink id in a side panel is not proof);
- never write `steps_json` directly;
- be recorded as a new row in the tables above (provider, model, input/output tokens, calls).
