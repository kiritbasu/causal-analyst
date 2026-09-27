# Grade calibration

Does an A–D grade mean something? `sweep.py` generates datasets with causal-data-generator, runs
`ca.py run` with the *correct* diagram (an oracle plan, so it tests the grading and the estimators,
not the interview), and compares the grade with the actual error.

```bash
python evals/calibration/sweep.py --out evals/calibration/results --seeds 2   # ~1 minute per dataset
```

Results from our run: [summary.md](summary.md), per dataset: [runs.csv](runs.csv).
