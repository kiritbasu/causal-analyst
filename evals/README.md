# Evaluations

We used the [skill-creator](https://github.com/anthropics/skills) loop: for each scenario, one Claude
subagent runs **with** the skill and one runs the identical prompt **without** it. Both are blind to the
answer, and assertions are graded against the known truth. All runs used **Claude Opus 5.5**.

Scenarios and assertions: [`evals.json`](evals.json). Scenario 2 uses a case from the CausalDS benchmark,
which we don't redistribute.

## Results

| Iteration | What changed | Pass rate with skill | Without skill | Time per run (with) | Tokens (with / without) |
|---|---|---|---|---|---|
| 1 | first version | 100% | 56% | ~30 min | 98k / 80k |
| 2 | one-thread numerics, bundled bounds / power / bad-control tools | 100% | 57% | ~2.6 min | 96k / 79k |
| 3 | causal diagram + sign-off step (baselines reused from iteration 2) | 100% | 50%* | ~3.1 min | 99k / 79k |
| 5 | codebook, alternative diagrams, structure check, planted-effect test; new scenario 4 only | 100% | 86%† | n/a | n/a |
| 6 | v0.2.0 rerun of scenarios 1–3 (baselines from iteration 2) | 100% | 50%* | ~7 min‡ | 102–114k / 79k |

\* Iteration 3 added a "shows a causal diagram" assertion that the baseline can't pass by design.
† Scenario 4: the baseline avoided all three traps (+7.4, 7.0–7.8) and showed what controlling for them would do, but gave no trust grade. On this case accuracy does not separate the arms.
‡ Most of the time is the optional CausalPFN cross-check (2–5 minutes on CPU). Estimates matched iteration 2: loyalty +$9.25 (7.43–11.07), benchmark null with bounds −0.295 to −0.214, sales calls grade D with 0–25 per 100.

### Where the skill made a difference

| Scenario | True answer | With skill | Without skill |
|---|---|---|---|
| Loyalty program, post-treatment trap | +$9.17 | +$9.25 (7.43–11.07), grade C | +$9.50 (8.3–10.7), no grade |
| Unmeasured confounder (benchmark) | not identifiable | null; bounds contain truth | null; bounds **exclude** truth; "almost certainly about −0.27" in iteration 1 |
| Sales calls chosen on gut feel | ≈ +5 per 100 | grade D, 0–25 per 100, test sized | "24 is a ceiling" (it. 1); "6 to 16 per 100" **misses** truth (it. 2) |
| AI training: misleading mediator name, collider, reverse causation | +7.5 | +7.55 (7.0–8.1), grade B, wrong diagrams shown (5.3, 2.5, 2.9) | +7.4 (7.0–7.8), traps avoided, no grade |

Estimation accuracy on clean cases was similar either way. The skill's value was honest ranges,
abstention, pre-registration, structure and a sized next step. That costs about 20% more tokens and
1–2 extra minutes.

### Non-discriminating assertions (both arms pass)

Excluding the obvious post-treatment column, avoiding a well-described mediator and collider (scenario 4), estimating the clean loyalty effect within 15%, refusing a
headline number for sales calls, and recommending an experiment. Frontier models already do these.

## Reproducing

1. Install the skill in your agent.
2. For each eval, start a fresh session with the listed files attached and paste the prompt.
3. Grade the output against the assertions. Keep the true answers away from the analysing session.

Please share results for other models (see [CONTRIBUTING](../CONTRIBUTING.md)).
