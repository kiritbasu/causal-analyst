# Business question (from the SME, head of inside sales)
"Do our sales calls actually drive purchases? Leadership wants to know how many extra purchases per 100 calls we get, so we can decide whether to hire more reps."

# Data: data.csv (one row per business account, last quarter)
| column | meaning | when measured |
|---|---|---|
| account_id | identifier | - |
| account_size | small / mid / large | at the start of the quarter |
| past_purchases | purchases in the previous year | before the quarter |
| industry | account's industry | at the start of the quarter |
| got_sales_call | 1 = a rep called the account this quarter | during the quarter |
| purchased_90d | 1 = the account bought within 90 days of the quarter start | end of the quarter |

# What the SME can tell you if asked
- Reps decide who to call. They pick accounts they have a feeling are "warm" / ready to buy, based on conversations, emails and gut feel. That judgement is not recorded anywhere.
- There was no random element in who got called.
- One account's call doesn't affect another account's purchase.
- The SME is not a data scientist.
