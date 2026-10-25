# Usage, runtime, and cost report

## Full-dataset run

This report describes the deterministic run that produced repository-root `output.csv`.

| Run detail | Value |
|---|---:|
| Requests processed | 518 |
| Output rows | 518 |
| COMPLETE | 154 |
| INCOMPLETE | 354 |
| NOT_APPLICABLE | 10 |
| Evidence files parsed | 94 |
| Observations extracted | 3,245 |
| Hosted model calls | 0 |
| Input tokens | 0 |
| Output tokens | 0 |
| Estimated hosted-model cost | $0.00 |

## Models and tools

The decision pipeline is Python. It classifies requests, resolves identities, matches evidence, applies policy, and writes `steps_json` without a language model.

| Provider | Model/tool | Purpose | Calls / usage |
|---|---|---|---|
| None (local) | RapidOCR via `rapidocr-onnxruntime==1.2.3` | Read 11 PNG console screenshots | Local OCR; no tokens or hosted calls |
| None | No LLM | Classification, identity, policy, planning | 0 calls |

PDF text is extracted with `pypdf>=4.0.0`. The runtime dependencies are Python's standard library, `pypdf`, and RapidOCR.

## Token and cost accounting

| Measure | Total | Average per request |
|---|---:|---:|
| Input tokens | 0 | 0 |
| Output tokens | 0 | 0 |
| Combined tokens | 0 | 0 |
| Hosted model calls | 0 | 0 |
| Estimated hosted-model cost | $0.00 | $0.00 |

Local OCR does not use hosted tokens and incurs no API cost. This cost estimate does not include local compute or development time.

## Runtime

| Run condition | Approximate wall time |
|---|---:|
| OCR cache available | About 10 seconds |
| Cold OCR pass over 11 PNG files | About 1 minute |

Times depend on the machine. Evidence is parsed once per process and cached in memory. The submitted package includes `agent/png_ocr_cache.json`, so an evaluator can reuse extracted screenshot text.

Measure runtime from the repository root with:

```bash
python3 code/main.py --run
```

## Verify the zero-token claim

1. `code/requirements.txt` should list `pypdf>=4.0.0` and `rapidocr-onnxruntime==1.2.3`; no model SDK is required.
2. The run reads no API keys and makes no network calls.
3. With the OCR cache, the run can be performed offline. Without the cache, RapidOCR still runs locally.
4. The expected summary ends with `obs=3245`. A count of 3,243 indicates that PDF extraction did not run successfully.

## Why screenshot OCR is local

The challenge guidance distinguishes a screenshot hyperlink from pixels showing a record. Local OCR reads the screenshot itself and avoids sending screenshots to a hosted vision model. The parser and deterministic planner, rather than an LLM, decide whether an observation supports a step.

If a hosted model is added later, record its provider, model, calls, input and output tokens, and estimated cost here. A model should only propose observations visible in the evidence and must not write `steps_json` directly.
