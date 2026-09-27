# Brief (from an e-commerce CRM manager)

"Did our 20%-off coupon email actually make people buy?" We want the extra purchases per 100 customers emailed.

## Columns in data.csv (one row per customer)

| column | what it is | when it's recorded |
|---|---|---|
| customer_id | customer identifier | - |
| orders_last_year | orders in the 12 months before send day | before send day |
| days_since_last_order | days since the last order | on send day |
| email_subscriber_years | years subscribed to the newsletter | on send day |
| country | shipping country | at signup |
| got_coupon_email | 1 = was sent the coupon email | on send day |
| opened_email | 1 = opened the coupon email | within 7 days of send |
| purchased_30d | 1 = made a purchase within 30 days of send day | 30 days after send day |

## Notes
- The email went to a random half of the list.
- Only people who were sent the email can open it.
- One customer getting the action does not affect the others.
- The person who wrote this is not a data scientist.
