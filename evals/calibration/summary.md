# Grade vs actual error (oracle plans)

40 generated datasets: the 8 yes/no cross-sectional scenarios x 4 levels, 1-2 seeds, 4,000 rows, budget quick, correct diagram given.

| tier   |   runs |   covers_truth |   median_error_in_se |   median_rel_error |
|:-------|-------:|---------------:|---------------------:|-------------------:|
| B      |     18 |           0.94 |                 0.77 |               0.32 |
| C      |     12 |           0.92 |                 1.11 |               1.18 |
| D      |     10 |         nan    |               nan    |             nan    |

By level:

| level        |   B |   C |   D |
|:-------------|----:|----:|----:|
| realistic    |   8 |   2 |   0 |
| starter      |  10 |   0 |   0 |
| tricky       |   0 |  10 |   0 |
| unanswerable |   0 |   0 |  10 |

Reading it: every Unanswerable dataset got D (no number). B and C ranges both covered the truth about
nine times in ten, but C estimates were much further off in relative terms (median 118% vs 32%), so
the grade tracks how far to trust the size of the number. The two misses were a Tricky dataset graded
C, and a Realistic statin dataset graded B: its partly recorded healthy-adherer driver biased the
estimate, and the oracle plan had no negative-control check that would have caught it. The
interview's domain step exists for exactly that case. Small study: one or two seeds per cell.
