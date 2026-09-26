# Changelog

## 0.3.0 (2026-09-26)

Domain knowledge, used carefully.

- Domain briefing step before the interview (`references/domain.md`): the usual traps for this kind of question become questions, controls, checks or alternative diagrams. New report section "What we know about this kind of question".
- Source tags on column readings and diagram arrows: you told us / from your brief / the data suggests / general knowledge, not confirmed.
- `suspected_hidden`: drivers the domain suggests but the data lacks; drawn dotted, cap the grade at C unless an instrument gives an agreeing estimate.
- `negative_control_outcomes`: outcomes the action can't change; a failed check caps the grade at C and adds a rough bias-removed planning figure.
- `expected_effect`: a pre-registered range from published evidence, shown against the estimate.
- `dismissed_findings` for structure-check flags the brief rules out; relative effect in the headline; simulation check fixed for yes/no outcomes near 0 or 1.
- New example and eval: statin adherence with a healthy-adherer effect the brief never mentions.

## 0.2.0 (2026-09-26)

Checks on the diagram itself.

- Codebook: `ca.py codebook` drafts what each column means and when it was recorded; the expert confirms. Unconfirmed meanings lower the grade.
- Reverse causation: the interview asks whether past outcomes drove who got the action; `outcome_baseline` names the before-the-action measure, and its absence is flagged.
- Alternative diagrams: re-estimates under user-named alternatives (`alternatives`, with `illustrative` for trap demonstrations), each control dropped, and each left-out column added. New report section "What if our diagram is wrong?".
- Structure second opinion: a light PC-algorithm search flags collider-like controls and unused columns linked to both action and outcome, as questions.
- Planted-effect simulation on the user's own data (`sim_reps` by budget); failure lowers the grade.
- Placebo uses 5 shuffles. Report diagram now draws every node and added arrow at full width. "Who gains most" only names a group when the difference is real.
- New example and eval: AI-training case with a misleading mediator name, a collider and reverse causation.
- Report polish from the v0.2.0 eval rerun: raw-gap label in the estimates table, exact IDs in the sample rows, a note that passing checks can't rescue a grade-D result, clearer bounds wording, assumptions marked as confirmed when the column sheet is confirmed.
- Test sizing is now suggested for grade B results too.

## 0.1.0 (2026-09-26)

First public release.

- Guided workflow: data profile, plain-language interview, causal diagram sign-off, pre-registered plan.
- Estimators: doubly robust ML (main), double ML, causal forest, regression, propensity weighting, g-computation for amount treatments.
- Diagnostics: overlap, balance, placebo, random common cause, subsample stability, Cinelli–Hazlett sensitivity, bad-control illustration.
- Abstention: grade D with Manski / Manski–Pepper bounds, instrument bounds and complier effect.
- Optional foundation-model cross-checks: CausalPFN (local) and TabPFN (hosted, opt-in).
- Designed HTML report (`ca.py report`) opening with a data overview (shape, column roles, distributions, sample rows; `report_sample_rows: 0` hides the rows), causal diagram drawn and explained in words right after the data (`ca.py dag`), test sizing (`ca.py power`).
