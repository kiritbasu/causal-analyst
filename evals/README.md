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
| 7 | domain briefing, negative controls, expected-effect check; new scenario 5 vs the v0.2.0 skill (not a no-skill baseline) | 100% | 71% (v0.2.0)§ | ~6 min | 118k / 111k |

\* Iteration 3 added a "shows a causal diagram" assertion that the baseline can't pass by design.
† Scenario 4: the baseline avoided all three traps (+7.4, 7.0–7.8) and showed what controlling for them would do, but gave no trust grade. On this case accuracy does not separate the arms.
§ Scenario 5 compares the new skill with the previous version, not with plain Claude. Both runs spotted the healthy-adherer effect unprompted and both checked injury admissions, but the v0.2.0 run had to do it by hand: its script still graded the result B while its own text said C, and it wrote no expected range before the run. Both planning figures landed near the truth (new: −2.2 per 100 from the built-in check; old: −2.3 to −3.5 from custom code). The honest conclusion: the model already had the domain knowledge; the new step makes using it systematic, graded and visible in the report.
‡ Most of the time is the optional CausalPFN cross-check (2–5 minutes on CPU). Estimates matched iteration 2: loyalty +$9.25 (7.43–11.07), benchmark null with bounds −0.295 to −0.214, sales calls grade D with 0–25 per 100.

### Where the skill made a difference

| Scenario | True answer | With skill | Without skill |
|---|---|---|---|
| Loyalty program, post-treatment trap | +$9.17 | +$9.25 (7.43–11.07), grade C | +$9.50 (8.3–10.7), no grade |
| Unmeasured confounder (benchmark) | not identifiable | null; bounds contain truth | null; bounds **exclude** truth; "almost certainly about −0.27" in iteration 1 |
| Sales calls chosen on gut feel | ≈ +5 per 100 | grade D, 0–25 per 100, test sized | "24 is a ceiling" (it. 1); "6 to 16 per 100" **misses** truth (it. 2) |
| Statin adherence with an unmentioned healthy-adherer effect | −2.0 per 100 | adjusted −4.5 flagged as too high by the injury check and trial range; planning figure −2.2; grade C | (v0.2.0 skill) same bias found by hand; script grade B |
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
