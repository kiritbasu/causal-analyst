# spec.json

The spec is the pre-registered plan. Write it after the interview and before running.
Paths may be absolute or relative to where you run `ca.py`.

| Field | Required | Meaning |
|---|---|---|
| `data` | yes | CSV, Parquet or Excel file |
| `treatment` | yes | Action column |
| `outcome` | yes | Outcome column (numeric; yes/no coded 0/1) |
| `treatment_type` | yes | `"binary"` (0/1) or `"continuous"` (an amount) |
| `contrast` | continuous only | `{"x0": low level, "x1": high level}` to compare |
| `estimand` | no | `"ATE"` (everyone, default) or `"ATT"` (those treated; binary only) |
| `confounders` | yes | Pre-treatment columns that may drive treatment and/or outcome. Use `[]` if none. |
| `excluded` | no | `{column: reason}` for columns deliberately not used (post-treatment, IDs, instruments used elsewhere). Shown in the report. |
| `instruments` | no | Columns that nudge treatment but affect the outcome only through it |
| `mediators` | no | Measured middle step (front-door; identification only in this version) |
| `randomized` | no | `true` if treatment was randomly assigned |
| `hidden_confounding` | yes | `"none_known"` or `"named_driver"` (SME named an unrecorded factor driving both) |
| `hidden_driver_note` | no | The SME's words about the hidden driver |
| `hidden_driver_label` | no | Short label (under ~40 characters) for the diagram, e.g. "rep's sense the account is warm". The diagram adds "Not in data:" itself, so don't write "unrecorded" |
| `outcome_range` | no | `[min, max]` the outcome can take, for no-instrument bounds (default: observed min/max; use `[0, 1]` for yes/no) |
| `extra_edges` | no | `[["from", "to"], ...]` arrows the SME adds between factors (e.g. `["income_k", "prior_quarter_spend"]`). Drawn in the diagram and used in the DoWhy check, which reports if the controls then need to change. |
| `allow_external_services` | no | `["tabpfn_api"]` to allow the hosted TabPFN cross-check (sends data to Prior Labs). Only with the SME's consent. |
| `causalpfn_max_rows` | no | Row cap for the local CausalPFN cross-check (default 20000) |
| `report_sample_rows` | no | Rows of raw data shown in the report's data section (default 5). Set `0` for sensitive data. |
| `codebook` | recommended | `{column: {"meaning", "recorded", "confirmed"}}`: your reading of each column and whether the SME confirmed it. Draft with `ca.py codebook`. |
| `outcome_baseline` | recommended | Column holding the outcome measured before the action (guards against reverse causation); also list it in `confounders` |
| `alternatives` | recommended | `[{"name", "why", "add": [...], "remove": [...]}]` or `{"name","why","confounders":[...]}`: plausible other diagrams to re-estimate under. Add `"illustrative": true` to one you include only to show a trap (e.g. controlling for a known consequence); it is drawn but does not lower the grade |
| `segments` | no | Pandas query strings for "who benefits more", e.g. `"tenure_months<12"`, `"urban==1"`. Each is compared automatically with the rest; don't also list the complement. |
| `main_method` | no | Default `"aipw_gbm"` (binary). Continuous main model is chosen by cross-validation automatically. |
| `budget` | no | `"quick"`, `"standard"` (default), `"thorough"` |
| `seed` | no | Default 1729; record it |
| `labels` | no | `{column: friendly name}` for the report |

What goes where:
- Measured before treatment and plausibly related to treatment or outcome → `confounders`.
- Caused by the treatment, or measured after it → `excluded` with reason "post-treatment".
- Identifiers, free text, and constant columns → `excluded`.
- Only affects outcome (not treatment) and pre-treatment → may go in `confounders` (it sharpens precision).

## Example: loyalty program (binary, observational)

```json
{
  "data": "data.csv",
  "treatment": "joined_loyalty",
  "outcome": "monthly_spend",
  "treatment_type": "binary",
  "estimand": "ATE",
  "confounders": ["income_k", "tenure_months", "age", "urban", "prior_quarter_spend"],
  "excluded": {"points_redeemed": "post-treatment: only members earn points", "customer_id": "identifier"},
  "hidden_confounding": "none_known",
  "segments": ["tenure_months<12"],
  "budget": "standard",
  "seed": 1729,
  "labels": {"joined_loyalty": "Loyalty membership", "monthly_spend": "Monthly spend ($)"}
}
```

## Example: amount treatment

```json
{"data": "data.parquet", "treatment": "discount_pct", "outcome": "units", "treatment_type": "continuous",
 "contrast": {"x0": 0, "x1": 10}, "confounders": ["region_size", "last_month_units"],
 "hidden_confounding": "none_known", "budget": "standard", "seed": 1729}
```

## Example: named hidden driver with an instrument

```json
{"data": "data.csv", "treatment": "got_call", "outcome": "bought", "treatment_type": "binary",
 "confounders": ["segment"], "instruments": ["random_dialer_slot"],
 "hidden_confounding": "named_driver", "hidden_driver_note": "reps chose customers they felt were ready to buy",
 "budget": "standard", "seed": 1729}
```
Here the script returns no main number (tier D) and reports the complier effect and bounds.
Without an instrument (drop `instruments`), it reports `bounds_no_instrument` instead.
