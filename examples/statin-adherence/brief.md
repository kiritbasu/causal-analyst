# Brief (from the pharmacy benefits analytics lead at a regional health insurer)

"We're writing the business case for a statin adherence programme (reminder calls, pharmacist check-ins). Finance wants one number: **how much does sticking to your statin reduce cardiac hospital admissions over the next year?** I'm in budget meetings all week, so please work from these notes."

## Columns in data.csv (one row per member who was prescribed a statin last year)

| column | what it is | when it's recorded |
|---|---|---|
| pid | member id | - |
| age | age in years | at prescription |
| female | 1 = female | at enrolment |
| diabetes | 1 = diabetes diagnosis on file | before prescription |
| smoker | 1 = current smoker on file | before prescription |
| ldl_baseline | LDL cholesterol, mg/dL | at prescription |
| admits_prior_yr | hospital admissions in the year before the prescription | before prescription |
| flu_shot_prior_yr | 1 = had a flu vaccination in the year before the prescription | before prescription |
| adherent | 1 = filled the statin for at least 80% of days in the first 6 months | first 6 months |
| cardiac_adm_12m | 1 = admitted for a cardiac event in the following 12 months | months 7-18 |
| injury_adm_12m | 1 = admitted for an accidental injury in the following 12 months | months 7-18 |

## Notes
- Taking the statin as prescribed is the member's own choice; there was no programme or outreach during this period.
- Claims data are complete for everyone in the file.
- One member's adherence doesn't affect another member's admissions.
