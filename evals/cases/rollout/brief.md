# Brief (from a growth lead)

"Did the new pricing page increase trial signups?" It went live region by region, so there was no clean A/B test.

## Columns in data.csv (one row per region per month)

| column | what it is | when it's recorded |
|---|---|---|
| region_id | region id | - |
| month | month number (1 = Jan last year) | - |
| market_size_k | addressable businesses in the region (thousands) | fixed |
| language | main site language | fixed |
| switched_in_month | month the new page went live here (0 = never) | - |
| new_pricing_live | 1 = new pricing page live in this region that month | monthly |
| trial_signups | trial signups that month | monthly |

## Notes
- Bigger markets got the new page first.
- Signups are seasonal (slower in summer).
- One region getting the action does not affect the others.
- The person who wrote this is not a data scientist.
