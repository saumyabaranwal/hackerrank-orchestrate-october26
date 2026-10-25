# Evaluation report

## Ghost Data Still Exists — deletion audit agent

## Executive summary

| Measure | Result |
|---|---:|
| Public-sample status accuracy | **32/32 (100%)** |
| Public-sample exact step structure | **18/32 (56%)** |
| Extra predicted steps on public sample | **0** |
| Missing public-sample steps | **19 of 193** |
| Full-dataset rows | **518** |
| Full-dataset status mix | **154 COMPLETE, 354 INCOMPLETE, 10 NOT_APPLICABLE** |
| Full-dataset observations | **3,245 from 94 files** |
| Determinism | Same input produces the same output |
| Hosted model use | None; 0 tokens and $0 estimated cost |

The public sample is the only split with known gold answers. Its cases were used during development, so these results are in-sample and do not predict hidden-test accuracy. No hidden gold is available for the 518-request run.

The implementation prioritizes precision: it avoids assigning a neighbor's record to the wrong person. This leaves some records unreported when the evidence does not identify their owner.

## 1. Data and evaluation method

- **Public sample:** `dataset/sample_deletion_requests.csv` compared with `dataset/sample_output.csv` (32 cases).
- **Full run:** repository-root `output.csv` compared with the 518 requests in `dataset/deletion_requests.csv`; no full-run gold answers are available.
- **Runner:** `python3 code/evaluation/main.py`.
- Organizer-only truth is not used by the prediction pipeline, and sample answers are not hardcoded.

The organizers confirmed that cases 39 and 55 are excluded from scoring because the available evidence cannot support the required claims. In particular, `evidence_32` shows archive presence for case 55, not whether restore is allowed or blocked. The output therefore makes no restore claim for that case.

## 2. Status accuracy

| Split | Measure | Result |
|---|---|---:|
| Public sample (32) | Exact `deletion_status` match | **32/32** |
| Public sample | Gold status mix | 10 COMPLETE, 22 INCOMPLETE, 0 NOT_APPLICABLE |
| Public sample | Exact step structure | **18/32** |
| Full run (518) | Rows and request order | **518; matches `deletion_requests.csv`** |
| Full run | Status mix | 154 COMPLETE, 354 INCOMPLETE, 10 NOT_APPLICABLE |
| Full run | NOT_APPLICABLE ids | `case_533`–`case_542` |
| Full run | Empty COMPLETE plans | None |

The 10 NOT_APPLICABLE cases match the non-deletion block in the request data. The public sample's remaining differences are missing resources; no sample status is flipped.

The largest INCOMPLETE plan in the current run is 14 steps. There are no cloned 70-step plans, no rows for `export_1842` (catalog link only, no evidence file), and no resource represented under two system IDs.

Cases 61 and 63 are INCOMPLETE in the current output: `object_19` cites `evidence_46`, and `marketing_001` cites `evidence_60`.

## 3. Step-level and field-level accuracy

The following comparison uses the ordered step arrays for the 32 public cases.

| Measure | Result |
|---|---:|
| Predicted steps | 174 |
| Gold steps | 193 |
| Extra predicted steps | **0** |
| Missing gold steps | **19** |
| Step precision | **100% (174/174)** |
| Step recall | **90.2% (174/193)** |
| Phase match on aligned positions | 174/174 |
| Operation and state match on aligned positions | 148/174 |
| System and resource match on aligned positions | 142/174 |

Exact structure is an all-or-nothing case measure: one missing step makes a case non-exact. Therefore, 18/32 does not mean that only 56% of individual steps are correct.

Field matches above are positional. A missing gold step shifts later positions and can make otherwise correct steps appear mismatched. They are intentionally strict and are not a set-based score.

### Missing sample resources

The 19 missing steps occur in 14 sample cases. They fall into two groups:

| Evidence gap | Examples | Why the agent omits the step |
|---|---|---|
| Gold-only identifiers | `account_004`, `audit_record_6645`, `audit_record_5569` | The identifiers do not appear in participant evidence or activity |
| Unattributed records | Identifier-less 404s and null-identifier analytics rows | The evidence does not establish which person owns the row |

The planner omits these rather than invent a resource ID or borrow a neighbor's record.

## 4. Ordering and contract checks

The full output has been checked for the required structure:

- Exactly 518 unique case rows, in the same order as `deletion_requests.csv`.
- Every `steps_json` value parses as JSON; step numbers are consecutive.
- Operations, phases, states, and phase/operation/system/resource ordering follow the problem statement.
- COMPLETE rows contain only verification steps with evidence references.
- INCOMPLETE rows use findings, then proposed remediation, then future verification; future steps have empty evidence references.
- NOT_APPLICABLE rows use `[]`.
- Every cited `evidence_*` file is captured no later than the case's `audit_at`.

## 5. Team evaluation cases

The evaluation runner reports all six team checks as passing.

| ID | Risk covered | Check |
|---|---|---|
| TC1 | Non-deletion requests | Invoice copy, phone correction, data download, and “stop marketing / leave account” stay NOT_APPLICABLE |
| TC2 | Historical identity | Resolves Camille's old email to `user_30` and includes the current email |
| TC3 | Neighbor attribution | Neither `account_5193` nor `account_6523` is stolen by cases 17 or 18 |
| TC4 | Request ordering | Output case IDs match the request file sequence |
| TC5 | Audit cutoff | No cited evidence file is captured after that case's `audit_at` |
| TC6 | Unknown restore state | Case 55 gets no restore operation from archive-presence-only evidence |

## 6. Failures found and changes made

| Failure | Change |
|---|---|
| Phrase classifier missed deletion wording and could confuse requests | Expanded marker lists and check non-deletion markers first |
| Substring identity matching confused IDs such as `user_21` and `user_210` | Use exact or word-boundary matching |
| A primary 404 hid a present replica | Treat any eligible present copy as present |
| Replica hostname appeared as the system ID | Map aliases such as `support_replica` to `support_platform` |
| Older snapshots displaced newer eligible evidence | Select the latest file captured by `audit_at` |
| Inner timestamps in later exports leaked future state | Use the evidence file's capture time for state |
| Nested cloud logs yielded no observations | Parse nested `message=` fields and relevant identity keys |
| Ungrouped syslog lines shared identities | Keep line identities separate and parse trace IDs |
| Catalog links were ignored | Use links to establish ownership only when an evidence record exists and timing is eligible |
| Archive presence was treated as restore-block proof | Emit restore steps only when restore state is known; case 55 has no restore operation |
| Missing PII state could be mistaken for redaction | Planner now distinguishes true, false, and unknown PII states |

### Remaining limitations

- The parser's `pii_from_mapping()` helper still returns false when it finds no recognized PII fields. The planner preserves unknown values, but this parser behavior means not every input format preserves uncertainty end to end. This should be improved by returning unknown when the fields are missing or the schema is not sufficient to establish redaction.
- The public sample was used to tune phrase lists and the 10-minute / 2-hour activity thresholds.
- The single-profile assumption may not cover people who genuinely have two live profiles.
- Legal-hold handling is implemented but is not exercised by the public sample.
- A parser failure could cause a relevant row to be missed.
- There is no hidden gold for the 518-case run, so its status distribution is a sanity check, not an accuracy score.

## 7. Reproduce the evaluation

```bash
python3 -m pip install -r code/requirements.txt
python3 code/main.py                 # generate output.csv
python3 code/main.py --score-sample  # score the public sample
python3 code/evaluation/main.py      # public sample and TC1–TC6
```

The full run documented here produced:

```text
rows=518  COMPLETE=154  INCOMPLETE=354  NOT_APPLICABLE=10  obs=3245
```
