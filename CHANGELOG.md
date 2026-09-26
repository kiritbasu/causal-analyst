# Changelog

## 0.1.0 (2026-09-26)

First public release.

- Guided workflow: data profile, plain-language interview, causal diagram sign-off, pre-registered plan.
- Estimators: doubly robust ML (main), double ML, causal forest, regression, propensity weighting, g-computation for amount treatments.
- Diagnostics: overlap, balance, placebo, random common cause, subsample stability, Cinelli–Hazlett sensitivity, bad-control illustration.
- Abstention: grade D with Manski / Manski–Pepper bounds, instrument bounds and complier effect.
- Optional foundation-model cross-checks: CausalPFN (local) and TabPFN (hosted, opt-in).
- Designed HTML report (`ca.py report`) opening with a data overview (shape, column roles, distributions, sample rows; `report_sample_rows: 0` hides the rows), causal diagram (`ca.py dag`), test sizing (`ca.py power`).
