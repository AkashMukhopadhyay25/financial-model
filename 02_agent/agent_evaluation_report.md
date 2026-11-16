# Agent evaluation: paraphrase consistency

Run `ad119a6bb920` on 2026-11-16 01:49 UTC. Every row is also in `ops_agent_evaluation`.
Expected results come from the deterministic engines, called directly (no language model).

## Stress Test: 16 of 16 phrasings consistent

| Case | # | Question | Expected | Observed | Trust | Pass |
|---|---|---|---|---|---|---|
| S1 Watchlist defaults | 1 | What happens to our expected credit loss if every Watchlist project slips to Past Due? | ECL increase 10,109.45 | 10,109.45 | REVIEW_RECOMMENDED | yes |
| S1 Watchlist defaults | 2 | If all the Watchlist names go into default, how much bigger does the reserve get? | ECL increase 10,109.45 | 10,109.45 | REVIEW_RECOMMENDED | yes |
| S1 Watchlist defaults | 3 | Stress test: migrate the whole Watchlist to default. What's the ECL impact? | ECL increase 10,109.45 | 10,109.45 | REVIEW_RECOMMENDED | yes |
| S1 Watchlist defaults | 4 | How much more would we have to provision if every project currently on the Watchlist became Past Due? | ECL increase 10,109.45 | 10,109.45 | REVIEW_RECOMMENDED | yes |
| S2 Ratings 5-6 default | 1 | If all Active projects rated 5 or 6 default, how much more would we need to set aside? | ECL increase 8,831.00 | 8,831.00 | REVIEW_RECOMMENDED | yes |
| S2 Ratings 5-6 default | 2 | What is the additional expected loss if our highest-risk projects (internal rating 5 and 6) all default? | ECL increase 8,831.00 | 8,831.00 | REVIEW_RECOMMENDED | yes |
| S2 Ratings 5-6 default | 3 | Assume every Active project with a risk rating of 5 or worse goes into default. Impact on ECL? | ECL increase 8,831.00 | 8,831.00 | REVIEW_RECOMMENDED | yes |
| S2 Ratings 5-6 default | 4 | How big is the reserve hit if the projects rated 5-6 fail? | ECL increase 8,831.00 | 8,831.00 | REVIEW_RECOMMENDED | yes |
| S3 Africa Watchlist + half drawdown | 1 | Stress Sub-Saharan Africa: Watchlist projects default and clients draw half of their undisbursed commitments. | ECL increase 4,122.44 | 4,122.44 | VALIDATED | yes |
| S3 Africa Watchlist + half drawdown | 2 | In Sub-Saharan Africa, what if the Watchlist projects default after drawing 50% of what is still undisbursed? | ECL increase 4,122.44 | 4,122.44 | VALIDATED | yes |
| S3 Africa Watchlist + half drawdown | 3 | Africa scenario: Watchlist goes Past Due and half of the undisbursed commitments get drawn first. ECL change? | ECL increase 4,122.44 | 4,122.44 | VALIDATED | yes |
| S3 Africa Watchlist + half drawdown | 4 | How much would expected credit loss rise if Sub-Saharan African Watchlist projects defaulted with a 50% drawdown? | ECL increase 4,122.44 | 4,122.44 | VALIDATED | yes |
| S4 Loss rate 75% | 1 | What happens to the reserve on today's Past Due projects if the loss rate is 75% instead of 60%? | ECL increase 1,899.05 | 1,899.05 | VALIDATED | yes |
| S4 Loss rate 75% | 2 | If loss given default rises to 75%, how much more ECL do we need on the existing Past Due book? | ECL increase 1,899.05 | 1,899.05 | VALIDATED | yes |
| S4 Loss rate 75% | 3 | Recompute expected credit loss on current Past Due exposure at a 75% loss severity. | ECL increase 1,899.05 | 1,899.05 | VALIDATED | yes |
| S4 Loss rate 75% | 4 | How sensitive is the reserve: Past Due projects at 75% LGD rather than the 60% we assume? | ECL increase 1,899.05 | 1,899.05 | VALIDATED | yes |

## Capital Allocation: 8 of 8 phrasings consistent

| Case | # | Question | Expected | Observed | Trust | Pass |
|---|---|---|---|---|---|---|
| A1 Prioritise vs caution | 1 | Which industry should IFC prioritise for new commitments, and which should it approach with caution? | prioritise Energy; caution Finance; limit Sub-Saharan Africa | **recommendation**: prioritise energy (growing in south asia, east asia & pacific), approach finance with caution, and l | VALIDATED | yes |
| A1 Prioritise vs caution | 2 | Where should new money go by sector, and which sector should we be careful with? | prioritise Energy; caution Finance; limit Sub-Saharan Africa | **recommendation**: prioritise energy (growing in south asia, east asia & pacific), approach finance with caution, and l | VALIDATED | yes |
| A1 Prioritise vs caution | 3 | Give me the industry to grow and the industry to slow down on for new commitments. | prioritise Energy; caution Finance; limit Sub-Saharan Africa | **recommendation**: prioritise energy (growing in south asia, east asia & pacific), approach finance with caution, and l | VALIDATED | yes |
| A1 Prioritise vs caution | 4 | For the next round of commitments, which sector is the best bet and which is the riskiest? | prioritise Energy; caution Finance; limit Sub-Saharan Africa | **recommendation**: prioritise energy (growing in south asia, east asia & pacific), approach finance with caution, and l | VALIDATED | yes |
| A2 Concentration | 1 | Where are we too concentrated, and what does the market outlook say about it? | prioritise Energy; caution Finance; limit Sub-Saharan Africa | **recommendation**: prioritise energy (growing in south asia, east asia & pacific), approach finance with caution, and l | VALIDATED | yes |
| A2 Concentration | 2 | Which region is over our concentration limit, and should we keep adding there? | prioritise Energy; caution Finance; limit Sub-Saharan Africa | **recommendation**: prioritise energy (growing in south asia, east asia & pacific), approach finance with caution, and l | VALIDATED | yes |
| A2 Concentration | 3 | Is any part of the portfolio too concentrated? What should we do about new commitments? | prioritise Energy; caution Finance; limit Sub-Saharan Africa | **recommendation**: prioritise energy (growing in south asia, east asia & pacific), approach finance with caution, and l | VALIDATED | yes |
| A2 Concentration | 4 | Concentration check: which regions should we limit and where should we grow instead? | prioritise Energy; caution Finance; limit Sub-Saharan Africa | **recommendation**: prioritise energy (growing in south asia, east asia & pacific), approach finance with caution, and l | VALIDATED | yes |

