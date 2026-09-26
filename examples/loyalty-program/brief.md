# Business question (from the SME, a retail marketing lead)
"Does joining our loyalty program actually raise monthly spend? I need the average effect across all our customers with a range I can trust, and I'd like to know if some customers benefit more (e.g. newer customers) so we can target the program."

# Data: data.csv (one row per customer)
| column | meaning | when measured |
|---|---|---|
| customer_id | identifier | - |
| income_k | household income, $k | at account creation |
| tenure_months | months as a customer | at the start of the period, before anyone joined |
| age | customer age | at account creation |
| urban | 1 = lives in an urban area | at account creation |
| prior_quarter_spend | total spend in the quarter before the launch ($) | before the program launched |
| joined_loyalty | 1 = joined the loyalty program | during the launch window |
| points_redeemed | loyalty points redeemed | during the outcome month |
| monthly_spend | spend in the outcome month ($) | the month after the launch window |

# What the SME can tell you if asked
- Joining was voluntary. Marketing pushed the program harder in cities and to people who already spent a lot.
- Only members can earn and redeem points.
- One customer joining does not affect other customers' spend.
- The SME is not a data scientist.
