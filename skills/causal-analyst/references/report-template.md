# Report: narrative.json

`ca.py report` builds the page. You supply the words in `narrative.json`; the script supplies
every number and chart from `results.json`. Write for the SME: plain words, short sentences, no
jargon without a translation. Keep the whole page readable in two minutes.

## Rules
- Numbers in your copy must be read from `results.json` (or `diagnostics.derived`), rounded for
  people ("about $9", "73%"). Never compute them in your head.
- The `answer` matches the trust tier: A "caused / raises by about"; B "most likely raises by
  about ..." and name the key assumption; C lead with the best estimate and the caveat in the same
  breath; D "We can't tell ... because ..." then what can be said and what would answer it.
- If the main 95% range includes zero, say the data are consistent with no effect.
- Use the SME's names for things (`labels`), and their unit ("per customer per month").
- Everything left open or assumed on the SME's behalf goes in `questions`.
- Mention foundation-model cross-checks only if they disagree with the main result or the SME asks.

## Fields (all optional except title and answer)

| Field | What it is |
|---|---|
| `eyebrow` | Short topic, e.g. "Delivery pass" |
| `title` | The question in the SME's words |
| `answer` / `answer_html` | One or two sentences, tier-worded. `answer_html` may use `<strong>` only |
| `value_prefix`, `value_suffix`, `decimals`, `value_scale` | Number format: `"$"`, `" per 100"`, decimals for detail numbers (hero numbers round to 2 significant figures unless `hero_decimals` is set). `value_scale` multiplies every displayed number: `100` turns a 0.25 difference in a yes/no outcome into "25 per 100" |
| `effect_label`, `unit` | Hero card label ("Effect of joining") and unit ("per customer per month") |
| `units` | What a row is, plural ("customers", "accounts") |
| `group_names` | `{"treated": "members", "untreated": "non-members"}` |
| `labels` | Friendly names for columns and segment queries, incl. `"not (<query>)"` |
| `data_title`, `data_text` | Header and one line for the data section (shape, column roles, distributions, sample rows) |
| `caution_bullets` | 1-3 short plain reasons behind the grade (translate `trust_reasons`) |
| `segment_card_title`, `segment_card_note`, `segment_title`, `segment_text` | Group comparison copy. Not shown at tier D (group effects share the same hidden bias). The hero card names a group only when a group difference is bigger than chance; otherwise it says "About the same for everyone" and uses `segment_card_note_similar` |
| `domain_title`, `domain_text`, `negative_control_note` | Copy for the domain-briefing section and the negative-control card (defaults are fine) |
| `third_card` | `{"title","text"}` hero card when there are no segments (e.g. "What would answer it") |
| `gap_title`, `gap_text`, `selection_label`, `action_label` | The raw-gap breakdown ("Most of the $35 gap isn't the program") |
| `methods_title`, `methods_text` | Method comparison header and one-paragraph read |
| `overlap_title`, `hidden_note`, `trust_title`, `trust_text` | Trust section copy |
| `bounds_title`, `bounds_text` | Tier D: what can still be said |
| `dag_confirmed` | `true` if the SME confirmed the diagram, `false` if drawn from a brief without confirmation (shows a status chip next to the diagram) |
| `dag_title`, `dag_text` | Header and one line for the diagram section (default "How we think it works") |
| `assumptions` | Optional `[{"text","status"}]`; by default the table lists the identification assumptions with an automatic status |
| `dag_note` | "Confirmed by you before the run." or, when no one could confirm it, "Drawn from the brief; not yet confirmed by you." |
| `alternatives_title`, `alternatives_text` | Header/intro for "What if our diagram is wrong?" |
| `naive_label` | Label for the raw gap when the real effect is bigger than it (the "raw gap understates the effect" view) |
| `trap_title`, `trap_text` | Why the excluded columns were left out |
| `data_issues` | `[{"title","text"}]` problems to check, never silently fixed |
| `next_steps` | `[{"title","text"}]` 1-3 concrete actions (a sized test, targeting, data to collect) |
| `questions` | `[{"title","text"}]` open questions and assumptions made for the SME |

## Translating diagnostics (for captions and bullets)

| Diagnostic | Plain words |
|---|---|
| propensity near 0 or 1 | "almost always / never got {treatment}, so we have few look-alikes to compare" |
| SMD after weighting < 0.1 | "after reweighting, the groups look alike on {traits}" |
| shuffled-action check passes | "giving {treatment} to random rows showed no effect, as it should (a sanity check on the software, not evidence about hidden bias)" |
| robustness value > strongest benchmark | "a hidden factor would need to be stronger than {X}, our strongest measured driver, to erase this" |
| robustness value > strongest benchmark, but the SME named a hidden driver | not reassurance: "a hidden factor would need to be {x} times stronger than {X}; the driver you named could well be that strong" |
| robustness value < strongest benchmark | "a hidden factor as strong as {X} could erase this; that is a caution, not evidence of bias" |
| complier effect (instrument) | "for the {units} whose {treatment} was changed by {instrument}, the effect was ..." |
| bounds (instrument) | "the average effect for everyone lies between {lo} and {hi}, under the instrument assumptions alone" |
| bounds_no_instrument mtr_mts | "if {treatment} never hurts and the {units} picked would have done at least as well anyway, the true effect is between 0 and {upper}" |
| power | "a fair test would need about {per_group} {units} in each group to spot a lift of {lift}" |

## When a profile flag contradicts the brief
If profile says a column is non-zero for some untreated units but the SME or brief says that
can't happen (e.g. "only pass holders get free deliveries"), report it under `data_issues`, keep the SME's
timing judgement for the analysis, and say which way it could matter.

## Example (delivery pass, tier C)

```json
{
 "eyebrow": "Delivery pass",
 "title": "Does the delivery pass make customers order more often?",
 "answer_html": "Yes, most likely by about <strong>0.6 orders per customer a month</strong>, and customers who live further away gain the most. Treat the exact size with some caution: it assumes nothing important about who bought the pass is missing from the data.",
 "value_prefix": "", "decimals": 2,
 "effect_label": "Effect of the pass", "unit": "orders per customer per month", "units": "customers",
 "group_names": {"treated": "pass holders", "untreated": "everyone else"},
 "labels": {"distance_km>10": "Over 10 km away", "not (distance_km>10)": "10 km or closer", "orders_prior_quarter": "Orders last quarter"},
 "caution_bullets": ["1 in 12 customers had few look-alikes to compare with.", "A hidden factor 60% as strong as last quarter's orders could erase it."],
 "segment_card_note": "Your hunch was right: the gap between the two groups is about 0.5 orders (range 0.2 to 0.8).",
 "gap_title": "Most of the 2.1-order gap isn't the pass",
 "gap_text": "Pass holders order 2.1 more times a month than everyone else. About 70% of that comes from who bought the pass.",
 "selection_label": "Who bought it", "action_label": "The pass",
 "trust_title": "Why the grade is C, not B",
 "dag_note": "Confirmed by you before the run.",
 "trap_text": "Free deliveries used are a result of having the pass. Treating them as a control flips the answer to a nonsense result.",
 "data_issues": [{"title": "Data issue to check", "text": "412 customers without a pass show free deliveries, but only pass holders should have any."}],
 "next_steps": [{"title": "Confirm with a small randomized test.", "text": "About 900 customers per group would detect a lift of 0.3 orders."}],
 "questions": [{"title": "How did customers end up buying the pass?", "text": "You weren't sure, so we treated it as self-selected."}]
}
```
