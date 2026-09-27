# Brief (from a head of customer success)

"Did the new onboarding checklist reduce churn in the first 90 days?" We need churned accounts per 100 to size the rollout.

## Columns in data.csv (one row per account)

| column | what it is | when it's recorded |
|---|---|---|
| account_id | account identifier | - |
| plan_tier | plan at signup (starter / pro / business) | at signup |
| seats | paid seats at signup | at signup |
| week1_active_users | users active in the first week | end of week 1, before the checklist decision |
| came_from_trial | 1 = converted from a free trial | at signup |
| got_checklist | 1 = account was given the onboarding checklist | in week 1 |
| checklist_items_done | checklist items completed | by day 30 |
| newsletter_opens | newsletter emails opened last quarter | before the action |
| app_rating | last app store rating given (1-5) | before the action |
| churned_90d | 1 = cancelled within 90 days | day 90 |

## Notes
- Customer success managers decided which accounts got the checklist, usually bigger or more active ones.
- Only accounts that got the checklist can complete items.
- One account getting the action does not affect the others.
- The person who wrote this is not a data scientist.
