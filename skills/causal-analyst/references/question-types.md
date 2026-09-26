# Question types this version handles

| SME question | Data needed | This version |
|---|---|---|
| Does doing X change Y? (yes/no action) | one row per unit, action 0/1, outcome, pre-treatment traits | Yes: `treatment_type: binary` |
| How much does more X change Y? (amount) | amount column | Yes: `treatment_type: continuous` with `contrast` |
| Who does it help most? | as above plus the traits that define groups | Yes: `segments` (pre-specified groups) + causal-forest spread |
| Was it randomized (A/B test)? | assignment column | Yes: `randomized: true` |
| Something unrecorded drives both, but a random nudge exists | instrument column | Complier effect + bounds (tier D for "everyone") |
| What changed after a rollout? (before/after, several periods) | panel over time | Not automated: explain that difference-in-differences or synthetic control is needed; offer to write a one-off analysis and label it outside the tested library |
| A cutoff decided who got it (score >= 600) | the running score | Not automated: regression discontinuity; same as above |
| Which of several actions works best? | multi-valued action | Not automated: run one binary comparison per action vs. control, flag the multiple comparisons |

When you go outside the tested library, say so in the report ("custom analysis, not part of
the tested toolkit") and keep the same rules: plan first, script every number, sensitivity checks.
