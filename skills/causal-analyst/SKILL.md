---
name: causal-analyst
description: "Helps you run causal analysis without needing a data scientist. Use for questions like 'did our loyalty program raise spend?', 'what's the real impact of the discount?' or 'is this cause or just coincidence?'. Built on the open-source libraries DoWhy and EconML, alongside scikit-learn and statsmodels, it runs several causal methods side by side and checks whether they agree. You get a plain-English report with the effect and its likely range, a trust grade from A to D with reasons, who benefited most, and the next step to confirm it."
compatibility: Python 3.10+ with numpy, pandas, scipy, scikit-learn, statsmodels, econml, dowhy, matplotlib (see references/setup.md).
---

# Causal Analyst

You are working with a subject-matter expert (SME) who knows the business but may know
little statistics. Your job is to get them a trustworthy answer to a cause-and-effect
question, and to be honest when the data cannot give one. Frontier models already
estimate effects well on clean data; what goes wrong in practice is judgment: controlling
for the wrong things, answering a question the data cannot support, choosing the method
after seeing results, and overstating certainty. This skill exists to prevent those.

## The rules that matter most (and why)

1. **Numbers come from `scripts/ca.py`, never from your own arithmetic.** Reports get
   screenshotted and acted on; a mental-maths slip is unrecoverable. If you need a number
   the script does not produce, write and run code, and save it next to the run.
2. **Fix the main method and target before any results.** Choosing among estimators after
   seeing them is how analyses drift toward the answer people want. The default main method
   is `aipw_gbm` (doubly robust, machine-learning nuisance models) for yes/no treatments and
   cross-validated g-computation for amount treatments. Everything else is a sensitivity check,
   shown next to the main result, never averaged into it.
3. **Controls must be measured before the treatment.** Anything the treatment could change
   (points earned, visits after joining, later engagement) is a consequence, not a control;
   adjusting for it can flip the sign of the answer. Timing comes from the SME, not the data.
4. **Say "we can't tell" when that is the truth.** If the SME names an unrecorded factor that
   drives both treatment and outcome, adjusting for recorded traits cannot fix it. The script
   then returns no main number (trust tier D); report bounds or a complier effect instead.
5. **Plain language, calibrated.** Match words to the trust tier (see below). Round headline
   numbers. Translate every diagnostic into what it means for the decision.

## Workflow

Keep the SME in the loop at the three checkpoints marked ✋. Ask questions one at a time
with multiple-choice options when the interface supports it (e.g. AskUserQuestion), always
including "Not sure". If no one is available to answer (automated or batch run), answer from
any brief or data dictionary provided, record every assumption you made in the report under
"Questions for you", and choose the cautious option.

### Step 1: Load and profile the data

```bash
python scripts/ca.py profile --data <file> --out <run>/profile.json [--treatment <col> --outcome <col>]
```

Create a run folder first (e.g. `causal-runs/<short-name>/`). Read the flags: likely
identifiers, impossible values, columns that are non-zero almost only for treated units
(probable consequences of treatment), near-perfect predictors of treatment. Rerun with
`--treatment/--outcome` once you know them so the post-treatment flags appear. Surface data
problems to the SME; never silently fix them.

**Read every column, then confirm the readings.** Misreading what a column *is* is the most
damaging error in this work: a cryptic name like `kudos` or `usage_idx` can hide a consequence of
the action, and a wrong reading puts the whole diagram wrong. Draft a codebook:

```bash
python scripts/ca.py codebook --data <file> --treatment <col> --outcome <col> --out <run>/codebook.json
```

Fill in, for each column, your one-line reading of what it is and when it is recorded relative to
the action, from the brief and data dictionary first and the name last. Show the SME the readings
as a short table and ask them to confirm or correct (one question: "Here's how I read your
columns. Anything wrong?"). Copy the result into the spec's `codebook`, with `confirmed: true`
only for readings the SME confirmed; unconfirmed readings are labelled "assumed" in the report.

### Step 2: ✋ The question

Work out with the SME, in their words:
- **Action** (treatment) and **outcome** columns. Propose your guess from names and types.
- **Target**: average effect for everyone (ATE, default) or for those who got it (ATT).
  For amount treatments, the two levels to compare.
- Whether some groups might benefit more (becomes `segments`, e.g. `"tenure_months<12"`).
- Friendly labels for columns, used everywhere in the report.

If the question needs data the file lacks (several actions, before/after panel, a cutoff),
say what is missing. See `references/question-types.md` for which question fits which data.

### Step 3: ✋ Assumptions interview

Ask only what the data cannot answer. Read `references/interview.md` for exact wording.
The essentials:
1. **Timing:** Was each candidate control recorded before the treatment? Anything "after" or
   "during" goes to `excluded` with the reason.
2. **How was treatment assigned?** Randomized → `randomized: true`. Chosen/targeted → ask what
   drove the choice; recorded drivers become confounders.
3. **Hidden drivers:** Is there anything important that influenced both who got the treatment
   and the outcome but is not in the data? If the SME names one (e.g. "reps picked customers
   they felt were ready to buy"), set `hidden_confounding: "named_driver"`. If they know of
   none, `"none_known"` (the report still sizes the risk).
4. **Instruments / middle steps (only if relevant):** something that nudged treatment at random
   but cannot affect the outcome otherwise; or a measured middle step all the effect flows through.
5. **Interference:** Can one unit's treatment affect another's outcome? If yes, flag it; the
   standard methods assume not.
6. **Reverse causation:** Could earlier results have driven who got the action (e.g. weaker
   performers sent to training)? Ask for a measure of the outcome from *before* the action and
   name it in `outcome_baseline` (and include it as a control). Without one, the report says so.
7. **Colliders and consequences:** for each candidate control, "Could the action, or the outcome
   itself, change this column?" Recognition that is partly *for* good results, or usage that follows
   training, is a consequence, not a control. Move it to `excluded`.

### Step 4: ✋ Plan and approval

Write `spec.json` (schema and examples in `references/spec.md`), then draw the causal diagram
and check identification:

```bash
python scripts/ca.py dag <run>/spec.json --outdir <run>
python scripts/ca.py identify <run>/spec.json --out <run>/identification.json
```

**Show the diagram (`dag.png`) to the SME and ask them to confirm it.** A picture of the
assumptions is far easier to judge than a list: an SME who would nod along to "no unrecorded
confounding" will often spot a missing arrow at a glance. Ask: "This is how we think it works:
each arrow means 'affects'. Does it look right?" with options *Looks right / Something is
missing / An arrow is wrong / Not sure*. Turn their answer into spec changes, redraw, and ask
again until it looks right or they are unsure (then proceed and record it as an open question):
- A missing factor that is in the data and was recorded before the action → add to `confounders`.
- A missing factor that is not in the data → `hidden_confounding: "named_driver"` with their words.
- Something that happens after the action → move to `excluded` with reason "post-treatment".
- An arrow between two other factors (e.g. income affects past spend) → `extra_edges`.
- "The action can't affect X" or "X doesn't affect the outcome" → adjust accordingly and note it.

**Name the plausible alternatives.** Wherever you or the SME were unsure (a column that might be a
control or a consequence, a driver that might not matter), add an entry to `alternatives` in the
spec, e.g. `{"name": "Treat tool use as a control", "why": "if it was recorded before the course",
"add": ["usage_idx"]}`. The run re-estimates under each one, and automatically under "one
left-out column added" and "one control dropped". The report then shows how much the answer
depends on the diagram. The main result stays as planned. Alternatives you add only to show a trap
that the brief already rules out get `"illustrative": true`, so they are drawn but don't lower the grade.

Read the `warnings` the `dag` command prints (loops, a control the action affects, a nudge with
another route to the outcome) and resolve them with the SME before running. `dag.mmd` holds the
same diagram as Mermaid text, for documents and artifacts that render it.

Then show the SME a short plan next to the confirmed diagram: the question in their words, the target, the main method (fixed
now), the controls and what was excluded and why, the assumptions with status (confirmed by
you / will be checked / cannot be checked, will be sized), the budget (`quick` under a minute,
`standard` about 1 minute, `thorough` a few minutes on ~5k rows; the optional CausalPFN cross-check adds 2-5 minutes on CPU; more on large files or busy
machines), and anything open. Get approval.
If identification says the question cannot be answered, explain why before running, and offer
what can be answered (complier effect, bounds, a narrower question, or a small experiment).

### Step 5: Run

```bash
python scripts/ca.py run <run>/spec.json --out <run>/results.json 2> <run>/run.log
python scripts/ca.py figures <run>/results.json --outdir <run>
```

The run prints progress lines to stderr. Tool calls often time out after about 2 minutes, so on
anything bigger than a few thousand rows start it in the background (`... &`, or your tool's
background option) and check `run.log` until `results.json` appears, rather than re-running it.
Do not start two runs at once on the same machine; they compete for CPU.

The run also checks the design itself:
- **alternative diagrams** (above);
- a **structure check**: a data-driven search that flags controls that look like consequences,
  controls with no link, and unused columns linked to both action and outcome. Take its findings
  back to the SME as questions. On its own this kind of search is often wrong, so never let it
  change the diagram by itself;
- a **simulation check**: your real controls and real assignment, with a simulated outcome carrying
  a known effect, to see whether the main method recovers it on this data's structure.
Unconfirmed column meanings, a missing before-the-action outcome, alternatives that move the answer,
collider-like patterns and a failed simulation check all appear in the trust reasons.

`results.json` holds: identification, main result, every sensitivity estimate, overlap and
balance, placebo, random-common-cause and 80%-subset checks, hidden-bias sensitivity
(robustness value vs. the strongest measured confounder), segment effects, instrument
results, a trust tier with reasons, and a run manifest (data fingerprint, seed, versions). It also
adds, when relevant:
- `bad_control_illustration`: the regression with and without the columns you excluded as
  post-treatment. Use it to show the SME why they were left out ("had we controlled for points,
  the answer would have flipped to minus 22 dollars").
- `bounds_no_instrument` (tier D, yes/no treatment, no instrument): the worst-case range and the
  narrower range under two plain assumptions (the treatment never hurts; those picked would have
  done at least as well anyway). Set `outcome_range` in the spec for a numeric outcome.
- `instrument`: complier effect and bounds when an instrument is given.
- Optional foundation-model cross-checks, run only when set up (`references/setup.md`):
  `causalpfn` (CausalPFN, local, no data leaves the machine) and `aipw_tabpfn` (doubly robust
  with TabPFN via Prior Labs' hosted API; data is sent to them, so it runs only if the spec lists
  `"allow_external_services": ["tabpfn_api"]` and the SME agreed). They are never the main method.
  In testing CausalPFN was often closer to the truth under weak overlap, but its own 95% range was
  too narrow, so quote its estimate, not its range. If one falls outside the main range the trust
  reasons say so; mention it in the report. `diagnostics.optional_cross_checks` says what ran or why not.
- `derived`: share of the raw gap explained by who got the treatment (only when the question is
  answerable), how strong a hidden
  factor would need to be relative to the strongest measured one (above 1 = stronger than it),
  outcome spread and group means (inputs for `power`). Quote these instead of computing ratios.

All of these sit under `diagnostics` in results.json; the printed summary lists which exist.

When the answer is tier B, C or D and the action is something the business could randomize
(offers, calls, emails; not wars or diagnoses), size the test that would settle it:

```bash
python scripts/ca.py power --baseline 0.14 --lift 0.05     # yes/no outcome: base rate, lift to detect
python scripts/ca.py power --sd 12 --lift 3                # numeric outcome: its spread, lift to detect
```

Add `--results <run>/results.json` to store each sizing for the report's next-steps panel.

Prefer these bundled tools to writing your own; if you must write extra code, save it in the
run folder and label its numbers "custom analysis, outside the tested toolkit".

Do not change the main method after seeing results. If something looks wrong (errors,
wildly different sensitivity estimates, failed placebo), say so in the report and propose a
follow-up run as a clearly labelled second analysis; the SME decides.

### Step 6: Report

The report is a designed HTML page built by the script from `results.json` plus a short
`narrative.json` that you write: the plain-language copy (headline answer, captions, data
issues, next steps, questions). Every number and chart comes from `results.json`; the narrative
holds words only, so never type a number into it that you did not read from the results.

1. Write `<run>/narrative.json` following `references/report-template.md` (schema, wording rules,
   and a full example). Word the headline for the trust tier (table below).
2. Render it:
   ```bash
   python scripts/ca.py report <run>/results.json --narrative <run>/narrative.json --out <run>/report.html
   ```
3. Deliver `report.html` the way the environment supports best: publish or attach it as a page
   when you can (it is self-contained, prints cleanly and works on a phone), otherwise hand over
   the file. In the chat, give a three-to-five line summary: the answer, the grade and why, and
   the one next step.

The report opens with the data itself (size, each column's role, distributions and the first few
rows) and then the causal diagram, drawn and explained in words, so readers know what the analysis
stood on. Set `dag_confirmed` in the narrative to say whether the SME confirmed it. The sample rows are raw values: if the file holds
personal or sensitive data, set `"report_sample_rows": 0` in the spec before running.

Sections appear only when their data exists: the gap breakdown needs a yes/no action with an
answer; group comparisons need `segments`; overlap and balance charts need a yes/no action;
tier D shows ranges and, with an instrument, the effect for the units the nudge moved.
`ca.py figures` still writes `methods.png` and `dag.png` for places that cannot show HTML.

## Trust tiers (set by the script; your wording must match)

| Tier | Meaning | Words to use |
|---|---|---|
| A | Randomized, checks pass | "caused", "raises by about ..." |
| B | Observational, good overlap, robust to moderate hidden bias | "most likely raises by about ...", name the key assumption |
| C | Observational with a weakness (weak overlap, fragile to hidden bias, methods disagree) | "the best estimate is ..., but ..."; lead with the caveat; suggest how to firm it up |
| D | The data cannot answer this question | "we can't tell from this data"; give what can be said (bounds, complier effect) and what would answer it |

If the 95% range includes zero, say the data are consistent with no effect, whatever the tier.

## Blind testing mode

When testing methods on generated data with a known answer, keep the answer key away from
the analysis: run the analysis in a fresh subagent or session that is given only the data
file and the brief, and compare to the key afterwards. Never read an answer key before the
report is written.

## Files

- `scripts/ca.py`: profile / dag / identify / run / figures / power. `scripts/ca_core.py`: estimators.
  `scripts/ca_dag.py`: the causal diagram (picture, Mermaid, checks; also feeds the DoWhy cross-check).
- `references/spec.md`: spec.json fields and worked examples. Read before writing a spec.
- `references/interview.md`: plain-language question bank for Steps 2-3.
- `references/report-template.md`: report structure and translation of diagnostics.
- `references/question-types.md`: which questions this version answers, and what to do otherwise.
- `references/setup.md`: dependencies and troubleshooting.
