# Genie phrasing test (run by a person in the app)

**Why:** the client's first requirement is the same figure however a question is asked. Our own agents are tested
automatically (`agent_evaluation_report.md`). Genie is tested by a person, because sessions do not call the Genie API
(team rule). Ask each phrasing in the app's Genie box, on the Overview or Portfolio analytics page, and note the figure
Genie returns.

**Pass rule:** Genie's figure equals the certified figure, which comes from `answers_register` (SQL in the
"Certified answers" library). The app also shows a trust level and a data-quality caveat under each Genie answer.
Record those too.

| # | Certified question (answers_register) | Certified figure | Phrasing | Genie figure | Trust level | Pass? |
|---|---|---|---|---|---|---|
| G1 | WS2_Q1_projects: Category A projects Past Due or on the Watchlist | **95 projects, 61 clients** | a. Which Category A projects are Past Due or on the Watchlist? | | | |
| | | | b. How many high-impact (Category A) projects are in trouble, either overdue or on the Watchlist? | | | |
| | | | c. Count the E&S category A projects whose performance status is Past Due or Watchlist. | | | |
| | | | d. Category A and distressed: how many projects and clients? | | | |
| G2 | WS2_Q2: provision for Past Due Category A projects (60% of disbursed) | **$3,311.72M** ECL on $5,519.53M Past Due disbursed | a. How much should IFC set aside for Category A projects that are Past Due? | | | |
| | | | b. What is the expected credit loss on Past Due Category A projects at a 60% loss rate? | | | |
| | | | c. Reserve needed for overdue Category A investments? | | | |
| | | | d. 60% of the disbursed amount of Past Due category A projects, in USD millions. | | | |
| G3 | Q12: Pending projects whose projected Board date has passed (not approved) | **237 projects** | a. List Pending projects whose Projected Board Date has passed but are not yet approved. | | | |
| | | | b. How many pending deals missed their planned Board date? | | | |
| | | | c. Which projects are late for Board approval? | | | |
| | | | d. Count Pending, unapproved projects with a projected Board date before their as-of date. | | | |
| G4 | Q28: approved total differs from the product sum by more than $1M | **146 projects** | a. Which projects have a Board-approved total that differs from the sum of their product allocations by more than $1M? | | | |
| | | | b. How many projects have product amounts that don't add up to the approved total (gap over $1 million)? | | | |
| | | | c. Find allocation mismatches above one million dollars. | | | |
| | | | d. Count projects where loan + equity + guarantee + risk management is more than $1M off the total approved. | | | |
| G5 | Q25a [Challenge]: MSME financing, excluding Dropped | **379 projects, $54,688.8M** approved | a. How many projects finance MSMEs, excluding Dropped, and how much was approved? | | | |
| | | | b. Small-business lending: number of projects and approved amount (not counting cancelled projects)? | | | |
| | | | c. What's our SME finance book in project count and dollars, Dropped excluded? | | | |
| | | | d. Projects whose main purpose is lending to micro, small and medium enterprises: count and total approved. | | | |
| G6 | Q13 [Challenge]: Active new renewable generation, Sub-Saharan Africa row | **21 projects, $2,872.89M** | a. Which Active projects have new renewable power generation as their main purpose? Count and approved amount by region. | | | |
| | | | b. How many active renewable generation projects do we have in Sub-Saharan Africa, and how much was approved? | | | |
| | | | c. New solar, wind or hydro generation projects that are Active, by region. | | | |
| | | | d. Active projects building new renewable capacity: count and approved $ per region. | | | |
| G7 | Expected credit loss for the whole portfolio (A11) | **$7,596.21M** | a. What is the expected credit loss across the whole portfolio? | | | |
| | | | b. How much should IFC provision for all Past Due projects? | | | |
| | | | c. Total ECL at 60% of Past Due disbursed, all categories. | | | |
| | | | d. Portfolio-wide reserve requirement? | | | |
| G8 | Low-risk projects: risk_flag = GREEN (Performing, Active) | **978 projects** | a. How many projects have no risk? | | | |
| | | | b. How many healthy projects do we have? | | | |
| | | | c. Count the low-risk projects. | | | |
| | | | d. How many Active projects are performing? | | | |

**Recording the result:** score each question group G1–G8 as "consistent" only if all four phrasings match. Put the
summary (e.g. "7 of 8 groups consistent, 30 of 32 phrasings") in the README's evaluation section. When a phrasing
fails, add it to the Genie space as an example question with the certified SQL (Genie space → Instructions →
SQL queries), then re-test it.
