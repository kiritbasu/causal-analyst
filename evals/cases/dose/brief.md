# Brief (from a category manager at a grocery chain)

"How many more units do we sell for each extra point of discount?" Finance wants to know where deeper discounts stop paying off.

## Columns in data.csv (one row per product-store week)

| column | what it is | when it's recorded |
|---|---|---|
| baseline_units | average weekly units over the previous 8 weeks | before the week |
| shelf_price | regular shelf price (€) | before the week |
| store_size_m2 | store sales floor (m²) | fixed |
| holiday_week | 1 = public-holiday week | calendar |
| discount_pct | price discount that week (%) | set the week before |
| stockout_flag | 1 = ran out of stock that week | end of the week |
| newsletter_opens | newsletter emails opened last quarter | before the action |
| app_rating | last app store rating given (1-5) | before the action |
| units_sold | units sold that week | end of the week |

## Notes
- Category managers put deeper discounts on items that were selling slowly.
- Holiday weeks get more promotions.
- The regular price is what the shelf label shows outside promotions.
- One product-store week getting the action does not affect the others.
- The person who wrote this is not a data scientist.
