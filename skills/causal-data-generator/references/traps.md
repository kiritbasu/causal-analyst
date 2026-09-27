# Traps by domain, and how to build them

Use these when writing a custom scenario: pick the 2–4 that genuinely occur in the user's domain.

| Trap | Where it shows up | Build it with | What a good analysis does |
|---|---|---|---|
| Targeting on past results / reverse causation | Marketing to big spenders; training for weak performers; discounts on slow sellers | a `prior_outcome` variable with a strong `to_treat` (positive or negative) | Adjusts for the before-the-action outcome |
| Consequence of the action ("post-treatment") | Points redeemed, emails opened, checklist items done | `post_treatment` with `kind: consequence`, often `treated_only` | Leaves it out |
| Collider | Satisfaction or recognition driven by both the action and the outcome | `post_treatment` with `kind: collider`, `from_treat` and `from_outcome` | Leaves it out |
| Middle step (mediator) | Tool usage after training; tasks automated by a feature | `mediator` with `share`; give it a `cryptic` name at Tricky | Doesn't control for it when the question is the total effect |
| Healthy-user / healthy-adherer | Medication adherence, screening, wellness programmes | a `hidden` driver, a `proxy` (flu shots), a `negative_control` (injury admissions) | Flags the bias; uses the negative control; grade C |
| Selection on unrecorded judgement | Sales reps' gut feel; managers' picks; carers signing people up | a strong `hidden` driver with no proxy (Unanswerable) | Says it can't be answered; gives bounds; proposes an experiment |
| Random nudge (natural experiment) | Seat draws, beta invites, pilot branches | `instrument` | Uses it to estimate the compliers' effect |
| Effects differ by group | Newer customers; starter plans; patients living alone | `heterogeneity` | Reports groups only when the difference is real |
| Weak overlap | Almost all big accounts get the action | the `overlap: weak` dial | Flags it, trims, cautions |
| Curved relationships | Diminishing returns, thresholds | the `nonlinear` dial; dose `shape: curved` | Flexible methods; not a single straight line |
| Score cutoff | Eligibility by risk or credit score | `design: cutoff`; `fuzzy` for partial take-up | Local comparison at the cutoff |
| Staggered rollout with growing effects | Regions or sites switching over time | `design: rollout` with `ramp_periods` and several `cohorts` | Cohort-by-cohort difference-in-differences, not plain two-way fixed effects |
| Switching after a bad period (Ashenfelter dip) | Sites or people adopting after a slump | `rollout.pre_dip` | A baseline that skips the dip |
| Adopters already on a different path | Fast-growing regions going first | `rollout.trend_selection` | Checks pre-trends; says the design fails |
| Misleading names | `usage_idx`, `kudos`, `flag_t` | `cryptic` names plus the `misleading_names` dial | Reads the codebook, not the name |
| Messy data | Missing values, noisy measures, irrelevant columns | the `missing`, `measurement_error` and `irrelevant` dials | Handles or flags them |
| No real effect | Any | the `zero_effect` dial | Finds nothing, and says so |

## Plausible effect sizes (rough guides)

- Loyalty programmes: 2–10% more spend. Coupon emails: 1–4 extra purchases per 100 recipients.
- Onboarding programmes: 2–6 fewer churned accounts per 100. Feature adoption: 5–15% more usage.
- Statin adherence: about 20–30% fewer major cardiac events relative to baseline, over years.
  Reminder texts: 3–8 more on-time refills per 100.
- Care management: 2–8 fewer readmissions per 100. Training: 5–15% more output, often fading.
- Sales calls: a few extra purchases per 100 calls, far smaller than the raw gap.
