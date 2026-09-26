# Contributing

Thanks for helping. The most valuable contributions are **evidence**:

1. **Eval results on other models or data.** Run the scenarios in `evals/` (or your own cases with a known answer) and open an issue with the pass rates, the model used, and anything the skill got wrong.
2. **New test cases with a known answer**, especially ones where naive analysis goes wrong (post-treatment controls, hidden drivers, weak overlap).
3. **Bugs in the toolkit.** Please include `results.json` or a minimal `spec.json` plus data that reproduces it.

Ground rules for code changes:

- Every number in a report must come from `scripts/`; the model writes words only.
- The main method is fixed before results. Don't add logic that picks the "best" estimate after the fact.
- Keep `SKILL.md` lean; put detail in `references/`.
- Run `pytest -q` before opening a pull request. It runs the whole pipeline on the loyalty example.
