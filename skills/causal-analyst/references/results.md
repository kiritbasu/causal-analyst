# What `ca.py run` produces

Read this when writing the narrative or when a trust reason needs explaining.

## Top level of `results.json`

- `identification`: whether the question can be answered, and by which route (adjustment,
  instrument, front-door, or not identifiable).
- `main_method`, `main_result`: fixed in the plan. `null` at tier D or if the main method failed.
- `estimates`: every method, shown next to the main one, never averaged into it.
  `double_ml` targets an overlap-weighted average (it leans towards units that could have gone
  either way), so it can differ from the main result when effects vary.
- `trust_tier`, `trust_reasons`: see the caps below.
- `rows_used`, `rows_dropped_missing`, `data_overview`, `dag`, `manifest` (data fingerprint, seed,
  versions, runtime).

## `diagnostics`

For an **amount** action the run gives the main contrast, the model-selection table and where the
two amounts sit in the data. The checks below are for yes/no actions only; say so in the report
rather than implying they ran.

- Overlap and balance; the **shuffled-action check** (giving the action to random rows should
  show nothing; a software and data sanity check, not evidence about hidden bias);
  random-common-cause; 80%-subset stability.
- `sensitivity`: robustness value vs the strongest measured control (how strong a hidden factor
  would need to be to erase the effect).
- `segments`: effect by group, with a range adjusted for the number of groups tested
  (`ci_adjusted`). Call a group difference real only when the adjusted range excludes zero.
- `missing_by_arm`: share of missing values in each used column, with and without the action.
- `alternatives`: the answer under the diagrams you named, plus automatic "one left-out column
  added" and "one control dropped".
- `structure_check`: a data-only second opinion (linear tests). Columns recorded before the action
  are never treated as consequences. Its findings are questions for the SME, never edits.
- `simulation_check`: your real controls and assignment, a simulated outcome with a known effect
  that varies by unit; does the main method recover it?
- `negative_controls`, `negative_control_adjusted`: estimates on outcomes the action can't change;
  when one fails, a **sensitivity band** for the main effect (if the same hidden difference also
  inflates it). Quote it as a band, never as the corrected answer.
- `plausibility`: the estimate against the `expected_effect` range written before the run.
- `bad_control_illustration`: the answer had you controlled for the excluded consequences.
- `bounds_no_instrument` (tier D, yes/no action): worst-case range, and a narrower one under two
  plain assumptions. Set `outcome_range` for a numeric outcome.
- `instrument`: complier effect (robust standard errors), first-stage strength, bounds.
- `optional_cross_checks`: CausalPFN (local) and TabPFN (hosted; only with
  `allow_external_services` and the SME's agreement). Never the main method; quote their
  estimate, not their range.
- `derived`: share of the raw gap explained by who got the action, hidden-factor strength needed
  relative to the strongest measured one, outcome spread and group means. Quote these instead of
  computing ratios yourself.

## Trust tier caps (all set by the script)

Start: **A** if randomized, else **B**. Then:

| Cap | When |
|---|---|
| D | The question isn't identifiable (a named hidden driver, no instrument or front-door); the main method failed |
| C | Front-door route; smaller group under 100 rows; weak overlap; shuffled-action check fails; a hidden factor half as strong as the strongest control could erase a non-zero effect; two or more same-target methods disagree beyond sampling noise; an alternative diagram moves the answer outside the main range; the simulation check fails; a negative control shows an effect; a suggested hidden driver; far outside the expected range; the outcome is missing 10+ points more often in one group |
| reason only | Imbalance after weighting, unconfirmed column meanings, no before-the-action outcome, collider-like patterns, a foundation-model cross-check outside the range, 5%+ rows dropped for missing values, a range that includes zero |

A range that includes zero never lowers the grade by itself: "no effect, measured well" can be B.

## Runtimes

About 1 minute at `quick` and 1 to 2 minutes at `standard` on ~5,000 rows, a few minutes at
`thorough`. The front-door route and CausalPFN (2 to 5 minutes on CPU) add more. Large files and
busy machines take longer.
