---
name: causal-data-generator
description: Creates realistic synthetic datasets for causal inference with a known true answer. Use when someone wants test data for a causal analysis, a practice or teaching dataset ("make me a dataset with a hidden confounder"), benchmark cases for methods, or demo data for an industry, e.g. "generate a loyalty-program dataset where the naive answer is wrong" or "I need a tricky churn dataset to test the analyst". It offers ready-made use cases or builds one from your description, asks about difficulty, and delivers data.csv plus an expert's brief, with a sealed answer key.
---

# Causal data generator

Make a dataset where the true causal effect is known, dressed as a real business problem, with
the traps real data has. The output looks like what a domain expert would hand an analyst:
`data.csv` and a `brief.md` in their words. The truth goes in a separate, sealed folder.

Every number comes from `scripts/cg.py`. It simulates explicit structural equations and computes
the truth from each row's potential outcomes, so the answer key is exact, not assumed.

## Workflow

Keep it short: 3–5 questions, then a one-screen plan to confirm. Ask with multiple-choice options
when the interface supports it (e.g. AskUserQuestion), always with a free-text way out. If no
one is there to answer, pick sensible defaults, say which, and go.

### 1. What is it for, and which story?

Run `python scripts/cg.py list` and offer the ready-made use cases grouped by industry, plus
"Describe your own". One question, two parts if the interface allows:

- **Purpose** (shapes the defaults): testing an analysis / teaching / benchmarking methods /
  a realistic demo.
- **Use case**: one of the list, or their own. Show each ready-made one as its title and
  one-line teaser.

**Their own use case.** Ask only what you can't infer, in one or two questions:
- the action and the outcome, and the unit (customer, store, patient…);
- how the action was decided: random, chosen by staff, self-selected, a score cutoff, or a
  rollout over time. This sets the design and the main trap.

Then write a scenario file with `references/scenario-schema.md`, starting from the closest
ready-made scenario in `scenarios/`. Give columns realistic names, ranges and units. Write the
brief notes as the expert would say them. Use your domain knowledge for the traps that
really occur in that field; `references/traps.md` lists them. Validate with
`python scripts/cg.py check <file>` before showing the plan. It generates every level and flags
any trap that doesn't bite or any method that should work but misses. Tune the coefficients until
the flags are gone, keeping effect sizes plausible. If the units interact (patients on the same
ward, stores in one region), set `interference_note` to say so honestly.

### 2. How hard?

| Level | What it contains |
|---|---|
| **Starter** | Recorded drivers only; clean data; a correct adjustment recovers the truth |
| **Realistic** | Targeting on past results, a consequence column, effects that differ by group, often an unrecorded driver that a recorded column only partly tracks (so even the best adjustment keeps some bias), a little missing data, some irrelevant columns |
| **Tricky** | Adds colliders, a middle step with a misleading name, weak overlap, curved relationships, extreme values, noisy measurement and cryptic names |
| **Unanswerable** | An unrecorded driver with nothing standing in for it; the honest answer is "we can't tell" |

Then offer, as one optional question, the dials: size (`--n`), `missing` (0–0.3), `overlap`
(good/weak), `nonlinear` (0–1), `heavy_tails`, `measurement_error`, `irrelevant` (number of
extra columns), `misleading_names`, and `zero_effect` (true effect set to 0, the best test
for false positives). For benchmarking, also offer a **set**: several seeds of the same
scenario.

### 3. ✋ Confirm the plan

```bash
python scripts/cg.py plan <id or scenario.json> --level <level> [--dials '{"missing": 0.1}'] [--n 8000]
```

Show the plan as printed: question, design, rows, action and outcome, the traps in plain words,
realism, and what the brief will say. Ask "Generate this?" (*Yes / Change the level / Change
something else*).

The plan names the traps and the effect size. **Use `--blind` on `plan` and `generate`**
whenever the data will be analysed blind: by the user, a colleague, or by you in this session
(step 5). Blind mode shows only the story, size, level and brief, and keeps the truth, traps and
quick estimates in the answer key. Decide this before you print anything: once you've seen the
truth, your own analysis is no longer blind.

### 4. Generate

```bash
python scripts/cg.py generate <id or scenario.json> --level <level> --out <folder>/<name> [--seed 42] [--n N] [--dials JSON]
python scripts/cg.py set      <id or scenario.json> --level <level> --out <folder>/<name> --seeds 5     # benchmarking
```

This writes:
- `<name>/data.csv` and `<name>/brief.md`: the files to share;
- `<name>-key/answer_key.json`: the targets (average effect for everyone, for those treated,
  per group, dose curve, effect at the cutoff, effect for those a random nudge moved), the traps,
  the correct adjustment set, and quick estimates showing which approaches work and which fail,
  and by how much;
- `<name>-key/generate.py`: a standalone, seeded script that regenerates the data exactly;
- `<name>-key/scenario.json`: the scenario used.

Read the printed summary. If a warning says a trap "may not bite on this draw", the trap is
there but weak for this sample (common with yes/no outcomes and small n). Offer a larger `--n`
or another seed. Don't quietly regenerate until it looks dramatic: the user asked for a
realistic dataset.

### 5. Deliver

Say what was made in two or three lines, e.g. "5,000 customers, 14 columns, level Tricky. The
brief is in the expert's voice. The answer key is sealed in `loyalty-key/`." Don't reveal the
truth or the traps unless the user asks, or chose a spoiler-full plan.

Then offer the hand-off: **"Want me to analyse it with causal-analyst?"** If yes:
- Best: start a fresh subagent (e.g. the Agent tool) with the causal-analyst skill, the paths to
  `data.csv` and `brief.md`, and the user's question. Nothing else. It has never seen the plan.
- If you can't start one, run causal-analyst yourself on the two files, and say plainly at the
  top of the result whether the run was blind. It was blind only if you used `--blind` and never
  opened the `-key` folder.
- Never read or pass the `-key` folder into the analysis. Afterwards the user can open the
  answer key and compare for themselves; don't score it unless asked.

## Principles

- **The truth is computed, not declared.** Report the realised values from the answer key, not
  the settings in the scenario. Clipping, groups and curves make them differ slightly.
- **Realistic beats dramatic.** Coefficients should give effect sizes and biases an expert in the
  field would find plausible. A trap that turns a +$10 effect into −$200 teaches the wrong lesson.
- **The brief is the expert's voice, not a hint sheet.** It says what they know and believe,
  including what they get wrong or leave out. At Tricky and Unanswerable, some traps are
  deliberately not mentioned.
- **Keep the answer sealed.** Anything that reveals the truth (answer key, scenario, generator
  script) lives in the `-key` folder.

## Files

- `scripts/cg.py`: list / plan / generate / set / check. `scripts/cg_engine.py`: the simulator.
- `scenarios/*.json`: 12 ready-made use cases across retail & marketing, SaaS & product,
  health & pharmacy, and people, sales & ops, covering yes/no actions, amounts, score cutoffs and
  rollouts.
- `references/scenario-schema.md`: how to write a scenario. `references/traps.md`: traps by
  domain, and how each maps to scenario fields.
