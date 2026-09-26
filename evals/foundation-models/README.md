# Foundation-model cross-check study

Compares the skill's main estimator (doubly robust with gradient boosting, 5-fold cross-fitting) with
CausalPFN on its own, and with CausalPFN's outcome predictions plugged into the doubly robust estimator.

- `gen.py` generates 12 semi-synthetic datasets with a known average effect (no hidden confounding):
  simple linear, nonlinear, strong confounding with poor overlap, and 30 columns; 3 seeds each.
  `keys.json` holds the true effects.
- `bench.py` runs the three estimators (`CAUSALPFN_WEIGHTS` may point at local weights).
- `results.csv` is our run: 12 synthetic sets plus the two loyalty datasets (14 rows per method).

| | Average error | 95% range covers truth | Time (CPU, 2–5k rows) |
|---|---|---|---|
| Doubly robust ML (main) | 5.2% | 14 / 14 | ~4 s |
| CausalPFN | 2.8% | 12 / 14 | ~25–55 s |
| Doubly robust with CausalPFN outcomes | 4.1% | 13 / 14 | ~25–55 s |

CausalPFN was most accurate, especially under poor overlap (within 3% where the main method came in
9–19% low), but its own intervals were too narrow. Small study; all data unconfounded given the
recorded columns, which is CausalPFN's home turf.

```bash
cd evals/foundation-models && python gen.py && python bench.py
```
