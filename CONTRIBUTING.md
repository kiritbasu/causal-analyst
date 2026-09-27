# Contributing

Thanks for helping. The most valuable contributions are **evidence**:

1. **Eval results on other models or data.** Run the scenarios in `evals/` (or your own cases with a known answer) and open an issue with the pass rates, the model used, and anything the skill got wrong.
2. **New test cases with a known answer**, especially ones where naive analysis goes wrong (post-treatment controls, hidden drivers, weak overlap).
3. **Bugs in the toolkit.** Please include `results.json` or a minimal `spec.json` plus data that reproduces it.

Ground rules for code changes:

- Every number in a report must come from `scripts/`; the model writes words only.
- The main method is fixed before results. Don't add logic that picks the "best" estimate after the fact.
- Keep `SKILL.md` lean; put detail in `references/`.
- Keep the skills free of eval material: `tests/test_contamination.py` fails if an eval's column names or answers appear in a skill.
- Update `references/results.md` when you change a grade rule in `ca_trust.py`.

## Running the tests

```bash
pip install -r requirements.txt -c constraints.txt -r requirements-dev.txt
pytest -q -n auto -m "not slow"   # about a minute
pytest -q -n auto                 # everything, including full pipeline runs (several minutes)
```

## Good first issues

- **A generator scenario for a new domain** (education, insurance, public policy, logistics). Copy the closest file in `skills/causal-data-generator/scenarios/`, edit it, and make `cg.py check` pass.
- **Eval results on another model.** Run the held-out cases in `evals/cases/` and open an "Eval result" issue.
- **Translate the report's fixed text** (headings and chart labels in `ca_report.py`) behind a `lang` setting.
- **Regression discontinuity** for score cutoffs: the generator already makes cutoff datasets with a known answer to test against.
- **Difference-in-differences** for staggered rollouts, tested the same way on the generator's rollout scenarios.
- **Calibration:** run `evals/calibration/sweep.py` with more seeds and propose changes to the grade rules it supports.
