# Interview question bank

Ask one question at a time. Offer options, always including "Not sure". Say briefly why you
ask; SMEs answer better when they know what the answer changes. Skip anything the brief or
data already answers.

## The question
- "What do you want to find out?" Options: Does doing X change Y? / Who does it help most? /
  What would happen if everyone (or no one) did X? / Not sure.
- "My guess is the action is **{t}** and the outcome is **{y}**. Right?"
- "Should the answer be the average for everyone, or only for those who actually {did X}?"
  (Why: they differ when the people who chose X are different from the rest.)
- "Are there groups you suspect benefit more or less?" (becomes segments)
- For "should we do more of it?" decisions (hire reps, widen a program), the relevant effect is
  on the units *not* treated today, who may respond less. Say so in the report; use `segments`
  or the untreated-group comparison where possible, and treat the average as an upper guide.

## What each column is (ask first)
- Show your codebook readings as a short table: column, what you think it is, when it's recorded.
  "Here's how I read your columns. Anything wrong?" Options: All correct / Some are wrong / Not sure.
- Why it matters: "A column that is really a result of the action, or of the outcome, will quietly
  skew the answer if I treat it as a background trait."

## Timing (the most important question)
- "Were {list} all recorded before {treatment happened}?" Options: Yes, all before / Some
  were recorded later / Not sure.
  Why: "If something was measured after, it may be a result of {treatment}; controlling for it
  would hide part of the effect, or even reverse it."
- For any column flagged as non-zero mostly for treated units: "Can {column} happen without
  {treatment}? When is it recorded?"

## Reverse causation and consequences
- "Could earlier results have affected who got {treatment}? For example, were people doing worse
  more likely to get it?" If yes or not sure: "Do you have {outcome} from before {treatment}?"
  (becomes `outcome_baseline` and a control).
- For any column that could be a reward or a by-product: "Could {treatment}, or {outcome} itself,
  change {column}?" If yes, it's a consequence; leave it out.

## Assignment and hidden drivers
- "How did {units} end up with {treatment}? Options: Picked at random / They chose it /
  We targeted them / Not sure."
- If targeted or chosen: "What did the choice depend on? Is all of that in the data?"
- "Is there anything important that affects both who gets {treatment} and {outcome} that we
  don't have in the file? For example {domain example}." Options: No, not that I know /
  Yes: ___ / Not sure.
  "Yes" with a concrete driver → `hidden_confounding: "named_driver"`. "Not sure" →
  `"none_known"` and say in the report that the sensitivity analysis sizes this risk.

## Instruments and middle steps (only when plausible)
- "Was there anything that nudged {treatment} more or less at random, like a lottery, a
  rollout order, a system outage, or timing, that couldn't affect {outcome} any other way?"
- "Does the effect work entirely through a step we can see (e.g. site visits)?"

## Interference
- "Could one {unit} getting {treatment} change another {unit}'s {outcome}? (Shared accounts,
  referrals, the same household or store.)" Options: No / Yes / Not sure.

## The diagram
- Show `dag.png`: "This is how we think it works: each arrow means 'affects'. Does it look
  right?" Options: Looks right / Something is missing / An arrow is wrong / Not sure.
- If "missing": "What is it, and is it in the data?" If "wrong": "Which arrow, and which way
  should it go (or should it not be there)?" Redraw and ask again.
- Prompt with one concrete example from their domain so "missing" feels answerable ("for
  example, could how engaged a customer already was affect both joining and spend?").

## Approval
- "Here's the plan. Approve and run, or change something?" List open questions next to the
  approve option and state the cautious default each will use.
