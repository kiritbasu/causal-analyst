# Brief (from the Head of People Analytics)

"Last quarter we rolled out an AI-tools training course. Leadership wants to know: **did the training raise productivity, and by how much?** I'm travelling this week and won't be able to answer questions, so please work from these notes."

## Columns in data.csv (names come from our HR system, sorry)

| column | what it is | when it's recorded |
|---|---|---|
| emp | employee number | - |
| cohort | department (eng, sales, ops) | at hire |
| yrs | years at the company | start of quarter |
| q_score | output score for the **previous** quarter (same scale as out_m) | before the course |
| slot_open | 1 if a course seat was open in the employee's time zone when sign-ups ran; seats were allocated by a random draw | at sign-up |
| flag_t | 1 = took the AI training course | during the quarter |
| usage_idx | how much the employee used AI tools, from tool logs | during the quarter, after the course |
| kudos | recognition points from peers and managers | end of quarter |
| out_m | output score this quarter (the productivity measure) | end of quarter |

## Notes
- Taking the course was voluntary. Managers nudged people who had a weak previous quarter to take it.
- Recognition points (kudos) are partly given for good output and partly for completing training.
- One person's training doesn't change another person's output.
