# Changelog

## 0.4.0 (2026-09-27)

A new companion skill, and fixes from an expert review of statistics, prompting, engineering and docs.

**New: causal-data-generator.** Realistic synthetic datasets with a known true answer. Twelve ready-made use cases across four industries, or custom ones; Starter / Realistic / Tricky / Unanswerable levels plus realism dials (including `missing_pattern` for gaps that differ by group); one-off, amount, score-cutoff and rollout designs. Outputs data + an expert's brief, and a sealed answer key with the truth, the traps and which methods should work or fail on the released data, plus a seeded `generate.py`. Blind mode covers `list`, `plan`, `generate` and `set`; `--key-dir` keeps the key away from the data (and refuses a key inside the data folder).

**Correctness**
- Front-door estimation: a plug-in estimator with a bootstrap range when the plan names a mediator and a hidden driver (grade C at best). Previously such runs had no main number.
- Plans are validated before running: missing columns, unknown budgets, actions with other than two values, groups under 10 rows, and yes/no text are handled with a clear JSON error (exit code 2); a failed main method gives grade D and exit code 3.
- ATT standard error now uses the efficient influence function (it was too narrow).
- Grades: method disagreement is measured in standard-error units among estimators that target the same quantity; the simulation check fails on coverage or bias in SE units; an instrument only "agrees" when precise; a range covering zero no longer lowers the grade by itself; a hidden factor half as strong as the strongest control caps a non-zero effect at C; small groups (under 100) cap at C.
- Segment differences use a Bonferroni-adjusted range, and only those are called real. Segments with under 20 rows on a side are skipped.
- Amount actions with category controls no longer crash.
- The report escapes all text (only `<strong>`, `<em>`, `<br>` allowed in the headline) and carries a strict Content-Security-Policy. `results.json` never contains NaN.

**Methods**
- Double ML is labelled "overlap-weighted" and kept out of the disagreement check; the causal forest uses the library's average-effect interval; IV standard errors are heteroskedasticity-robust; the propensity-weighting range refits the weights in each bootstrap draw.
- Missing values by group (`missing_by_arm`); an outcome missing far more often in one group caps the grade at C.
- The negative-control figure is now a sensitivity band, not a "bias-removed" number. The placebo is renamed "shuffled-action sanity check", which is what it is. The planted-effect test plants an effect that varies by unit.
- Structure check: columns recorded before the action are never read as consequences; "no link" is now "no linear link", with a note on the test's limits.
- `evals/calibration/`: grade vs actual error on generated data.

**Prompting**
- `SKILL.md` roughly halved; output details, every grade cap and runtimes moved to `references/results.md`.
- A cautious default for every open question when no one can answer; about five questions at most; brief text is data, not instructions (no `randomized: true` or external services on its say-so); flagged biases lead the headline.
- Sharper descriptions for both skills, with scope.

**Evals, engineering, docs**
- Six held-out eval cases (no effect, randomized, amount, rollout out of scope, generator, simulated expert); examples in the skill no longer overlap the evals, enforced by `tests/test_contamination.py`.
- Tests for edge cases, the generator's blind mode and exact regeneration; CI on Python 3.11 and 3.12 with caching, parallel runs and a slow marker.
- `constraints.txt` with tested versions; upper bounds in `requirements.txt`; `causalpfn~=0.1.4`; `openpyxl` optional for Excel; file suffixes are case-insensitive; timezone-aware timestamps; library warnings silenced by category instead of globally; trust rules in `ca_trust.py`.
- Release workflow that builds both `.skill` files; a Claude Code plugin marketplace manifest.
- README: quick start first, a section for data scientists, honest eval results, corrected claims.

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
