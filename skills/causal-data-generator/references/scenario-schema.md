# Writing a scenario

A scenario is a JSON file. Start from the closest file in `scenarios/` and edit it. Validate it
with `python scripts/cg.py check my.json`, which generates every level and prints the truth next
to the plain comparison.

## How the simulation works (so the numbers make sense)

- Every recorded driver is generated first, possibly depending on earlier ones
  (`depends_on`) and on hidden drivers (`from_hidden`).
- Effects act on each driver's **standardized recorded value** (one standard deviation = 1).
  So `"to_outcome": 9` means one SD more of this column adds 9 outcome units. For a yes/no or
  count outcome, it adds 9 to the log-odds or log-rate, so keep those coefficients small
  (0.1–1). `"to_treat"` is on the log-odds of getting the action (0.3 is mild, 0.8 strong,
  1.5 very strong). The `overlap: weak` dial (default at Tricky) multiplies all of these by 2.2,
  so tune at Realistic and check Tricky.
- The action is drawn from those drivers; its intercept is calibrated to hit `treatment.share`.
- The outcome under both "with" and "without" is computed for every row from the same random
  draws. The truth is the average difference, after clipping to the allowed range.
- Levels switch items on and off: any item with `"min_level"` / `"max_level"` exists only
  within that range. Order: `starter < realistic < tricky < unanswerable`.

## Top level

| field | meaning |
|---|---|
| `id`, `title`, `teaser`, `industry` | Shown in `cg.py list` |
| `question`, `ask` | The expert's question and one line of context (goes in the brief) |
| `sme` | Who is speaking, e.g. "a retail marketing lead" |
| `unit`, `units` | One row is a… ("customer", "customers") |
| `design` | `cross_section`, `cutoff` or `rollout` |
| `n` | Rows (or units, for a rollout) |
| `default_level`, `levels` | Default level; optionally restrict the offered levels |
| `id_col` | `{"name", "start", "meaning"}` identifier column |
| `estimand` | `ATE` (default) or `ATT` |
| `level_dials` | `{level: {dial: value}}` scenario-specific realism overrides |
| `level_overrides` | `{level: {...}}` deep-merged into the scenario from that level upward, e.g. `{"tricky": {"rollout": {"trend_selection": 1.5}}}` |

## Action and outcome

```json
"treatment": {"name": "joined_loyalty", "type": "binary", "share": 0.4,
              "meaning": "1 = joined the loyalty program", "recorded": "during the launch window", "cryptic": "jl_flag"},
"outcome":   {"name": "monthly_spend", "type": "continuous", "base": 85, "noise_sd": 22, "min": 0, "decimals": 2,
              "meaning": "...", "recorded": "..."},
"effect":    {"ate": 10, "unit_label": "$ per customer per month"}
```

- Outcome `type`: `continuous` (`base`, `noise_sd`, `min`/`max`), `binary` (`base_rate`), or
  `count` (`base_rate` as a mean). For yes/no and count outcomes, `effect.ate` is on the
  probability / mean scale and is calibrated exactly.
- **Amounts** (`"type": "dose"`): `min`, `max`, `step`, `grid` (levels reported in the answer
  key), `width` (spread of doses), and `effect` either `{"shape": "linear", "per_unit": 2.5}` or
  `{"shape": "curved", "max_effect": 70, "scale": 12}` (diminishing returns).

## Recorded drivers: `variables`

```json
{"name": "income_k", "meaning": "household income, $k", "recorded": "at account creation",
 "dist": {"type": "lognormal", "median": 62, "spread": 0.35}, "clip": [15, 400], "decimals": 0,
 "to_treat": 0.3, "to_outcome": 9, "depends_on": {"tenure_months": 0.3}, "from_hidden": {"U_engaged": 0.7},
 "role": "prior_outcome", "noisy": true, "cryptic": "inc", "min_level": "realistic", "to_treat_from": "realistic"}
```

- `dist.type`: `normal` (mean, sd), `lognormal` (median, spread), `uniform` (low, high),
  `binary` (p), `poisson` (mean), `category` (levels, probs; effects follow the level order).
- `role`: `prior_outcome` (the before-the-action measure of the outcome, the reverse-causation
  trap), `proxy` (a recorded stand-in for a hidden driver; give it `from_hidden`), or `running`
  (the score in a cutoff design).
- `noisy: true` means that at a measurement-error setting above 0 the recorded value gets noise,
  so adjusting for it leaves some bias.
- `to_treat_from` / `to_outcome_from`: the effect only switches on from that level. Use it to
  make Starter a clean randomized version.

## Hidden drivers: `hidden`

```json
{"name": "U_engaged", "label": "how engaged the customer already is", "to_treat": 0.3, "to_outcome": 4, "min_level": "realistic"}
```

These are never written to the data. If some recorded column has `from_hidden` pointing to one,
it is proxied: adjustment is the best available but still biased. If nothing proxies it, the
question is unanswerable by adjustment. Pair it with a note in the brief when the expert would
know about it.

## Other structures

| field | shape | trap it creates |
|---|---|---|
| `instrument` | `{"name", "p", "strength", "meaning", "recorded"}` | A random nudge; the answer key adds the compliers' effect and a Wald estimate |
| `mediator` | `{"name", "from_treat", "share", "base", "noise_sd", "meaning", "cryptic"}` | A middle step carrying `share` of the effect; controlling for it hides that share. Continuous outcomes only (use a rate rather than a yes/no) |
| `post_treatment` | list of `{"name", "kind": "consequence" or "collider", "from_treat", "from_outcome", "treated_only", "leak_share", ...}` | Columns that must not be controlled for; `treated_only` makes them zero for the untreated (e.g. points only members earn) |
| `heterogeneity` | `{"variable", "below" / "above" / "equals", "extra"}` (or `"extra_ratio"` for yes/no outcomes), `"label"` | The effect differs by group; the answer key reports each group |
| `negative_control` | `{"name", "type", "base_rate", "from_vars", "from_hidden", ...}` | An outcome the action can't change but a hidden driver does: a built-in bias check |
| `irrelevant` | list of `{"name", "meaning", "recorded", "dist"}` | Noise columns. Yours are used first; generic ones fill up to the `irrelevant` dial |
| `cutoff` | `{"running", "threshold", "label", "fuzzy", "p_above", "p_below", "bandwidth", "truth_window"}` | The action switches on at a score; truth is the effect at the cutoff |
| `rollout` | `{"periods", "cohorts": [start periods], "never_share", "ramp_periods", "season_amp", "time_trend", "pre_dip", "trend_selection", "level_selection", names}` | Staggered adoption over time; `ramp_periods` makes effects build up (misleads two-way fixed effects), `pre_dip` makes units switch after a bad period, `trend_selection` makes adopters already diverge (breaks parallel trends) |

## Brief and answer key text

- `notes`: `[{"text", "min_level", "max_level"}]` are the expert's statements, in their words.
  Leave some traps unmentioned at higher levels; that is the point of Tricky.
- `traps`: `[{"name", "text", "min_level"}]` explains the traps in the answer key and the plan.
- `interference_note`, `sme_note`: optional replacements for the brief's last two lines.

## Sanity rules

- The effect size should be plausible for the field (check `references/traps.md` and your own
  knowledge; search if you can).
- `check` prints the plain comparison next to the truth for every level. At Starter the gap
  should be modest. At Realistic and above, the plain comparison should clearly miss.
- Rows are independent draws. If the story has repeated units (a ward observed monthly), either
  frame a row as one unit, or use `design: rollout`, which has proper unit and period structure.
- Keep `n` large enough for the design: yes/no outcomes and rare actions need 5,000+ rows.
  Rollouts need 40+ units and a never-adopting group. Cutoffs need 10,000+ rows so enough sit
  near the threshold.
