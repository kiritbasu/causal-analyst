# Brief (from a product manager)

"Does turning on the AI assistant make users spend more time in the product?" We want the average lift in weekly active minutes.

## Columns in data.csv (one row per user)

| column | what it is | when it's recorded |
|---|---|---|
| user_id | user identifier | - |
| prior_weekly_min | average weekly active minutes, month before launch | before launch |
| account_age_months | months since the user joined | at launch |
| role | job role | at signup |
| desktop_app | 1 = mainly uses the desktop app | at launch |
| assistant_on | 1 = turned on the AI assistant | during the launch month |
| weekly_active_min | average weekly active minutes, month after launch | month after launch |

## Notes
- Anyone could turn the assistant on. Heavy users tended to try it first.
- One user getting the action does not affect the others.
- The person who wrote this is not a data scientist.
