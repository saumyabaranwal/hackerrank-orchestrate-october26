# Evaluation report: Ghost Data Still Exists

## 0. Summary

| Question | Answer |
|---|---|
| Does the agent get the required decision right? | Yes on the public sample: **32/32** `deletion_status` |
| Does it invent steps? | **0 extra steps on the 32-case sample.** Full-run extras are unknown (no hidden gold). |
| What does it miss? | **19 of 193** gold steps (about 9.8%), all unnamed leftovers or gold-only ids |
| Does a rerun change anything? | No. Cached Gemini classify + deterministic planner; no live network with the shipped caches |
| What is not known? | Hidden-eval step-level score. Only the 32-case sample has gold |

Evaluated data:

- **Public sample:** `dataset/sample_deletion_requests.csv` vs `dataset/sample_output.csv` (32 cases).
- **Full run:** 518 rows in root `output.csv` (`case_33`–`case_550`). No gold available.
- **Runner:** `python3 code/evaluation/main.py`.

We do **not** use organizer-only truth, and nothing from `sample_output.csv` is hardcoded into the agent. Extra steps are treated as more harmful than missing steps (contest Q&A), so precision is favoured over recall.

> **Caveat on the sample score.** Thresholds and phrase lists were tuned while looking at the 32 public cases. The sample numbers are therefore *in-sample*. They show the logic works, not how it generalizes to the hidden 518.

---

## 1. Case-level status accuracy

| Split | Metric | Result |
|---|---|---|
| Public sample (32) | `deletion_status` exact match | **32/32 (100%)** |
| Public sample | Status mix | 10 COMPLETE, 22 INCOMPLETE, 0 N/A (matches gold) |
| Public sample | Exact structure | **18/32** (catalog/PNG ids attach only if link or screenshot time is inside `[requested_at, audit_at]`) |
| Full run (518) | Rows produced | 518, same `case_id` order as `deletion_requests.csv` |
| Full run | Status mix | **154 COMPLETE, 354 INCOMPLETE, 10 NOT_APPLICABLE** |
| Full run | N/A ids | `case_533`–`case_542` only |
| Full run | Observations | **3245** from 94 files |

Status is the primary decision. Remaining sample gaps are **missing resource ids**, never flipped COMPLETE/INCOMPLETE.

After the nested-log parser fix, the 518-row file has **no cloned 70-step plans**. Largest INCOMPLETE is **14** steps. Empty COMPLETE: **none**. Dual-system (same `resource_id`, two `system_id`s): **0**. `export_1842` appears in **0** rows.

`case_61` / `case_63` are **INCOMPLETE** (`object_19` cite `evidence_46`, `marketing_001` cite `evidence_60`). `case_55` is COMPLETE without a restore step: `evidence_32` shows archive presence, not permission (organizers exclude `case_39` and `case_55`).

---

## 2. Step-level and field-level accuracy

Compared as ordered `steps_json` arrays on the 32 sample cases.

| Metric | Result |
|---|---|
| Cases with exact step structure (phase, operation, system, resource, state) | **18/32 (56%)** |
| Predicted steps | 174 |
| Gold steps | 193 |
| Extra predicted steps (precision errors) | **0** |
| Missing gold steps (recall errors) | **19** |
| Step precision | **100%** (174/174, since 0 extras) |
| Step recall | **90.2%** (174/193) |
| Phase match on aligned prefix | 174/174 |
| Operation + state match on aligned prefix | 148/174 |
| `system_id` + `resource_id` match on aligned prefix | 142/174 |

**How to read this**

- Exact-structure is all-or-nothing per case: one missing id fails the row. 18/32 is not "56% of the agent".
- The aligned-prefix rows (148/174, 142/174) compare by position. When a missing gold step shifts later steps, positional comparison under-counts correct steps. A set-based comparison would be higher; we report the stricter positional figure.
- When we emit a step, we do not emit a *neighbour's* leftover. We under-report identifier-less 404s and anonymized analytics rows that carry neither this person's email nor `user_id`. This is the intended trade given extra-step penalties.

**The 14 sample cases that miss a resource (19 steps)**

| Case | Missed gold resource(s) | Why we leave it |
|---|---|---|
| `case_04` | `account_004` | Gold-only id — not in participant evidence or activity |
| `case_18` | `account_5521`, `audit_record_6645` | `audit_record_6645` is gold-only; account is unnamed leftover |
| `case_20` | `account_5037`, `audit_record_5569` | `audit_record_5569` is gold-only |
| `case_03`, `21`, `25`–`28` | analytics ids (`analytics_9406`, …) | Null-identifier analytics in mixed dumps |
| `case_22`, `23`, `29`, `31`, `32` | account ids without identifiers | Identifier-less 404 / unique-assignment refused |

**Structural rules, all verified on the full run**

- COMPLETE rows contain only `VERIFICATION` steps, each with a non-empty `evidence_id`.
- INCOMPLETE rows are FINDING, then REMEDIATION, then VERIFICATION; future work has empty `evidence_id`.
- N/A rows are `[]`.
- Cited `evidence_*` `captured_at` ≤ that case's `audit_at` (TC5).

---

## 3. Sequence accuracy

Within each predicted list:

- Phase order is always FINDING, REMEDIATION, VERIFICATION.
- Within a phase: contest operation order, then `system_id`, then `resource_id`.
- On the 18 exact-match cases, sequence matches gold 18/18.
- On the 14 partial cases, emitted steps still obey the table. Gold differs only because the missing resources would have slotted in by `resource_id` sort.

---

## 4. Team test cases

Runnable via `python3 code/evaluation/main.py`. All seven **PASS**.

| ID | Risk covered | Probe | Pass criterion | Result |
|---|---|---|---|---|
| **TC1** | Non-deletion must not authorize erasure | Four synthetic texts: invoice copy, phone correction, data download, "stop marketing / leave account" | Classifier returns `is_deletion_request = False`, so planner yields `NOT_APPLICABLE` + `[]` | PASS |
| **TC2** | Ghost copies live under old addresses | Resolve `camille.bernard86@outlook.com` (case_30) | `user_30`, `matched_on=historical_email`, identity set also contains `camille.bernard@outlook.com` | PASS |
| **TC3** | Never steal a neighbour's account | Plan `case_17` and `case_18` | Neither `account_5193` nor `account_6523` appears in `steps_json` | PASS |
| **TC4** | Request order | `output.csv` vs `deletion_requests.csv` | Same `case_id` sequence | PASS |
| **TC5** | Audit cutoff | Every cited `evidence_*` | `captured_at` ≤ that case's `audit_at` | PASS |
| **TC6** | Restore unknown ≠ blocked | Plan `case_55` | No restore ops from archive-presence-only PNG | PASS |
| **TC7** | PII unknown ≠ redacted | `pii_from_mapping` | `{}` / no identifier keys → `None`; empty identifier keys or `ANONYMIZED` → `False`; populated email → `True` | PASS |

**Why these:** TC1 N/A trap (`case_533`–`542`). TC2 historical identity. TC3 extra-step penalty. TC4/TC5 submission contract. TC6 excluded-case honesty (`case_39`/`case_55`). TC7 parser three-state PII.

---

## 5. Failures found and fixes

| Failure | What we saw | Fix |
|---|---|---|
| Classifier misses | Early list missed "deleting", "left behind", Spanish/French verbs | Broader marker list; **non-deletion markers checked first** |
| `user_21` matched `user_210` | Substring match linked the wrong person | Word-boundary / exact `user_id` match |
| Replica ghost | Primary 404, failover still PRESENT | Any present copy at audit time means present |
| `support_replica` as `system_id` | Grader expects `support_platform` | `SERVICE_ALIASES` map |
| Old evidence preferred | Cited `evidence_02` over later `evidence_92` | Use latest file captured at or before `audit_at` |
| Future snapshot leak | A Sep 17 bundle stamped inner Sep 15 made support look already redacted | Use **file** capture time for state; later files may only teach ownership |
| Nested `message="key=\\\"value\\\""` logs | `cloud_runtime_export_*.log` produced 0 observations; empty COMPLETE on eval cases | Flatten inner `message=` KV; treat `function` as service; `scan_key` / `matched_value` / `correlation_key` as emails |
| Syslog identity bleed | Ungrouped lines shared one merged identity; `data_flow_4750` attached to the wrong people | Do not merge identity across ungrouped lines; parse syslog `tr-*` as `trace_id` |
| Catalog LINK unused | 12 `LINK_RESOURCE_IDENTITY` events ignored | Ownership when a file exists; PNG OCR for `object_19` / `marketing_001`; attach only if link/shot is inside `[requested_at, audit_at]` |
| Unknown PII treated as redacted | Planner mapped `None`→`False`; parser `pii_from_mapping()` returned `False` when identifier keys were absent | Planner keeps `Optional[bool]`; parser returns `None` unless identifiers are present or explicitly stripped (`email: null`, `[REDACTED]`, `ANONYMIZED`) |
| Archive presence as restore blocked | `case_55` cited `evidence_32` `VERIFY_RESTORE_BLOCKED` | Restore steps only if `restore_allowed` is known True/False |
| Two accounts for one email | Historical 404 `account_6523` plus later `account_4092` | Keep **one** USER_PROFILE, the newest at audit |
| Support PII hidden | Later snapshot with `pii=false` masked `REPORT_EXPOSED_PII` | At-audit export wins |
| Log `service=` as `system_id` | Lookup component leaked into `system_id` | Emit `system=` (the store), never `service=` |

### Known remaining failures (intentionally not "fixed")

| Gap | Cause | Why we leave it |
|---|---|---|
| 14 sample cases miss a resource (19 steps) | Identifier-less 404s / null analytics in multi-user dumps | Cannot prove whose row it is |
| `account_004`, `audit_record_6645`, `audit_record_5569` | Not present in participant evidence or activity | Would require inventing ids |
| `export_1842` | LINK only, no evidence file | Do not invent PRESENT/ABSENT |
| Legal-hold path untested on real data | Public sample has none | Wired as RETAIN to `VERIFY_RECORD_PRESENT` |

Chasing 32/32 exact structure by inventing ids would overfit the sample and add extras on the hidden 518.

---

## 6. Threats to validity

- **In-sample tuning.** The 10-minute margin and 2-hour window were chosen to keep sample cases correct. They are precision gates, not derived constants.
- **Phrase-list classifier.** Perfect on the sample and on the N/A block, but a new wording could be missed (fails closed to N/A).
- **Single-profile assumption.** If someone truly has two live profiles, we remediate only the newest.
- **Absence as proof.** If a row sits in a file the parser failed to read, we would call it absent.
- **No hidden gold.** The 518-row status mix is a sanity check, not an accuracy measurement.
- **Unknown ≠ false.** A missing PII or restore flag is not proof the record is redacted or restore-blocked.
- **OCR cache.** Submitted zip includes `png_ocr_cache.json`. A cold RapidOCR pass can drift on glyphs; the cache keeps the 518 run bit-identical.

---

## 7. Full-dataset sanity (the run that wrote `output.csv`)

```text
python3 code/main.py --run
# rows=518  COMPLETE=154  INCOMPLETE=354  NOT_APPLICABLE=10  obs=3245
```

Checks after write:

- [x] 518 unique ids, `case_33`–`case_550`, order = `deletion_requests.csv` (TC4)
- [x] every `steps_json` parses as JSON
- [x] N/A arrays are empty (`case_533`–`case_542`)
- [x] COMPLETE steps are all `VERIFICATION` with non-empty `evidence_id`
- [x] no COMPLETE with `[]`
- [x] no cited `evidence_*` after that case's `audit_at` (TC5)
- [x] `case_55` has no restore ops (TC6); `case_61`/`case_63` INCOMPLETE from PNGs
- [x] `export_1842` nowhere; gold-only ids nowhere
- [x] two consecutive runs produce an identical file (deterministic)

## 8. Reproduce

```text
python3 -m pip install -r code/requirements.txt
python3 code/main.py                 # writes output.csv
python3 code/main.py --score-sample  # sample scoring
python3 code/evaluation/main.py      # sample + TC1–TC7
```
