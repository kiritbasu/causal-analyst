# Domain briefing: what usually goes wrong in this kind of question

Read this in Step 3, before the interview. You know a lot about most domains; the SME knows
their own process. Use your knowledge to **ask better questions and plan checks**, never to
decide on the SME's behalf or to tune the answer. Everything you contribute is tagged
`"source": "general knowledge"` until the SME confirms it.

## Write the briefing (5 minutes, before any results)

In the spec, fill `domain_notes`:

```json
"domain_notes": {
  "domain": "statin adherence and hospital admissions",
  "usual_drivers": ["age", "diabetes", "smoking", "prior admissions", "health-seeking behaviour"],
  "known_traps": [
    {"name": "Healthy-adherer effect", "source": "general knowledge",
     "why": "People who take medicines as prescribed also look after their health in other ways, which lowers admissions on its own.",
     "handled": "Flu vaccination used as a partial stand-in; injury admissions used as a check; sized below."}
  ]
}
```

Then turn each item into one of:
- **A question for the SME** ("Do members who stick to their statin also tend to get flu shots and
  keep appointments?"). Their answer changes `source` to `"sme"`.
- **A control or stand-in** (a recorded column that tracks the suspected driver, e.g. flu shots
  for health-seeking behaviour). Add it to `confounders`; note it in the codebook.
- **A suspected hidden driver** the data can't record: `suspected_hidden`. It is drawn in the
  diagram, caps the grade at C, and is sized by the hidden-factor chart. Use `hidden_confounding:
  "named_driver"` instead only when the SME confirms a strong unrecorded driver (that makes it D).
- **A negative-control outcome**: a recorded outcome the action cannot plausibly change but the
  suspected driver would (injury admissions for a heart drug; last year's spend for a new
  programme). `negative_control_outcomes`. An apparent "effect" on it exposes hidden bias.
- **An alternative diagram** in `alternatives`.
- **An expected range** for the effect, from published evidence or benchmarks, in the outcome's
  units: `expected_effect`. Write it before the run; it flags implausible answers and never moves them.
  If web search is available, search for it; otherwise use what you know and say so in `basis`.

## Common traps by domain (starting points, not a checklist to recite)

| Domain | Trap | What it looks like | Typical response |
|---|---|---|---|
| Health, pharmacy | Healthy-adherer / healthy-user | Adherent or screened people do better on everything | Proxies (vaccination, screening), negative-control outcomes (injuries), expected-effect check vs trials |
| Health | Confounding by indication | Sicker people get the treatment, so it looks harmful | Severity measures before treatment; ask how treatment was decided |
| Health, subscriptions | Immortal time | Treated group must survive long enough to be counted as treated | Fix the start of follow-up at the decision point |
| Marketing, loyalty | Targeting the already-engaged | Offers go to big spenders | Prior spend as `outcome_baseline`; negative control: spend *before* the offer |
| Sales | Cherry-picking warm accounts | Reps call who they think will buy | Usually `named_driver` → D; ask for any randomness in assignment |
| HR, training | Self-selection of the motivated; managers nudging weak performers | Volunteers differ; regression to the mean | Prior performance as `outcome_baseline`; random seat draws as instruments |
| Product, SaaS | Power users adopt features first | Feature users retain better regardless | Prior activity; negative control: retention before launch |
| Pricing, promotions | Promotions timed to demand | Discounts run in peak weeks | Season / week controls; ask how timing was chosen |
| Education | Selection into programmes by ability or parents | Enrolled students were already ahead | Prior test scores as `outcome_baseline` |
| Operations | Regression to the mean after a bad period | Interventions follow a spike, which fades anyway | Baseline from several prior periods |

## Guardrails

- Your knowledge is about the domain in general; the SME knows *this* process. When they
  disagree with you, follow them and record the disagreement as an open question.
- Do the briefing before seeing any estimate. An expected range written after the run is worthless.
- Keep it short: 2-4 traps that genuinely apply, not a textbook list.
- In the report, every contribution of yours shows "general knowledge, not confirmed".
