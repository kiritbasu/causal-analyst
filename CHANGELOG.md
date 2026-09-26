# Changelog

## 0.2.0 (2026-09-26)

Checks on the diagram itself, prompted by Adam Kucharski's "Confounded by confounders" (2026).

- Codebook: `ca.py codebook` drafts what each column means and when it was recorded; the expert confirms. Unconfirmed meanings lower the grade.
- Reverse causation: the interview asks whether past outcomes drove who got the action; `outcome_baseline` names the before-the-action measure, and its absence is flagged.
- Alternative diagrams: re-estimates under user-named alternatives (`alternatives`, with `illustrative` for trap demonstrations), each control dropped, and each left-out column added. New report section "What if our diagram is wrong?".
- Structure second opinion: a light PC-algorithm search flags collider-like controls and unused columns linked to both action and outcome, as questions.
- Planted-effect simulation on the user's own data (`sim_reps` by budget); failure lowers the grade.
- Placebo uses 5 shuffles. Report diagram now draws every node and added arrow at full width. "Who gains most" only names a group when the difference is real.
- New example and eval: AI-training case with a misleading mediator name, a collider and reverse causation.

## 0.1.0 (2026-09-26)

First public release.

- Guided workflow: data profile, plain-language interview, causal diagram sign-off, pre-registered plan.
- Estimators: doubly robust ML (main), double ML, causal forest, regression, propensity weighting, g-computation for amount treatments.
- Diagnostics: overlap, balance, placebo, random common cause, subsample stability, Cinelli–Hazlett sensitivity, bad-control illustration.
- Abstention: grade D with Manski / Manski–Pepper bounds, instrument bounds and complier effect.
- Optional foundation-model cross-checks: CausalPFN (local) and TabPFN (hosted, opt-in).
- Designed HTML report (`ca.py report`) opening with a data overview (shape, column roles, distributions, sample rows; `report_sample_rows: 0` hides the rows), causal diagram drawn and explained in words right after the data (`ca.py dag`), test sizing (`ca.py power`).
