# Business case and adoption plan

All figures below are **assumptions, stated so they can be challenged and replaced** with the CFO Office's own numbers.
The calculation is simple on purpose: a reader can redo it in a minute.

## 1. Value case

### Assumptions (conservative on purpose)

| # | Assumption | Value | Basis |
|---|---|---|---|
| V1 | Effort to prepare one Board risk pack today | 2 analysts × 15 working days = **30 analyst-days** | Brief: "close to three weeks to prepare"; we assume only two analysts |
| V2 | Board risk packs per year | **4** (quarterly) | Typical Board risk cycle |
| V3 | Monthly management packs per year | **8** (the other months), at **5 analyst-days** each | A much smaller monthly version |
| V4 | Ad hoc portfolio questions per year | **120** (about 10 a month), at **half a day** each | Recurring questions like the 30 in WS1 |
| V5 | Effort with Cloudstruck | Board pack **5 days**; monthly pack **2 days**; ad hoc question **0.1 day** | Figures are certified and pre-assembled; analysts still check, add judgment and present |
| V6 | Fully loaded cost of an analyst-day | **USD 600** | Placeholder, deliberately low; replace with IFC's rate |

### Result

| Work | Today (analyst-days a year) | With Cloudstruck | Saved |
|---|---|---|---|
| Board risk packs (V1, V2) | 4 × 30 = 120 | 4 × 5 = 20 | **100** |
| Monthly packs (V3) | 8 × 5 = 40 | 8 × 2 = 16 | **24** |
| Ad hoc questions (V4) | 120 × 0.5 = 60 | 120 × 0.1 = 12 | **48** |
| **Total** | **220** | **48** | **172 analyst-days ≈ 0.75 of an analyst's year** |

At V6 that is about **USD 100,000 a year** of analyst time, redeployed from rebuilding numbers to analysis.
Every input is set low: the case holds even if only the Board packs (100 days, about USD 60,000) are counted.
With busier assumptions (three analysts per pack, 20 questions a month, USD 800 a day) the saving is about
450 analyst-days, or USD 360,000; we treat that as upside, not the claim.

### Value that is harder to price, but matters more

- **Decisions in the meeting, not three weeks later.** Directors' follow-up questions are answered live, with the SQL
  behind each figure.
- **No more conflicting figures.** One definition per measure. The two figures most likely to be confused are now
  always labelled: Category A expected credit loss ($3.31B) and whole-portfolio ECL ($7.60B).
- **Earlier warning.** 215 clients show risk signals; 42 are high priority. Stress tests size the downside in seconds,
  e.g. +$10.1B of expected loss if every Watchlist project defaulted.
- **Capital where it performs.** The allocation view shows Energy as our strongest industry (the market agrees) and
  Sub-Saharan Africa over the 25% concentration limit. That is the kind of insight that shapes the next round of
  commitments.
- **Data quality improves at the source.** 1,260 flagged projects are routed to four owners with plain-language
  messages, instead of being fixed again in each spreadsheet.

### Running cost (estimate at list prices; measure in the pilot)

| Item | Basis | Approx. per month (USD) |
|---|---|---|
| SQL warehouse (Genie, app pages, agent queries) | Serverless 2X-Small, 4 DBU/hour × ~$0.70 ≈ $2.80/hour, only while running (stops after 10 idle minutes); 4–8 hours per working day | 250–500 |
| Databricks App | Medium, 0.5 DBU/hour, always on, ~$0.75–0.95 per DBU | ~300 |
| Agent model (open-weight, pay per token) | ~500 agent questions a month | < 20 |
| Genie | No separate fee; runs on the SQL warehouse | included |
| Monthly pipeline run | Serverless job, ~15 minutes plus reruns | 10–30 |
| Storage | A few GB of tables | < 5 |
| **Total** | | **≈ 600–900 a month ≈ 7,000–11,000 a year** |

This is the extra usage only; IFC's Databricks platform itself is assumed to exist. Per-DBU prices vary by cloud,
region and contract. Against the conservative saving of about USD 100,000 a year, the return is roughly **10×**.

### Measuring the actual cost

The cost drivers are the serverless SQL warehouse (queries are cached for 10 minutes, so page views are cheap), the
Databricks App (one small instance) and Foundation Model API tokens (about 5–15 seconds of model time per agent
question). Measure the actual cost during the pilot from Databricks' billing tables:

```sql
SELECT usage_date, billing_origin_product, sum(usage_quantity) AS dbus
FROM system.billing.usage
WHERE usage_date >= current_date() - INTERVAL 30 DAYS
GROUP BY ALL ORDER BY usage_date;
```

## 2. Adoption plan

**People trust a number when they can see where it came from, and when someone accountable has looked at it.** The
product is built around that: every figure shows its SQL; the app labels each answer Green, Amber or Red with
reasons; nothing is decided without a person.

| Step | What happens | Who | Measure of success |
|---|---|---|---|
| 1. Champions | Two CFO Office analysts use Cloudstruck for the next monthly pack alongside the old process | CFO Office lead | Figures match; time spent |
| 2. Train | 45-minute session per team: the Overview, asking Genie, reading the trust level, the two agents, sending for review | Champions | Every analyst completes one pack task |
| 3. Switch | The next Board risk pack is built from the Board briefing page; spreadsheets kept only as a fallback | CFO | Pack ready in days, not weeks |
| 4. Close the loop | Credit Risk Committee works its review queue; data owners clear their issues | Committee chair, data owners | Open review items and data issues fall month on month |
| 5. Govern | Monthly: rerun the agent evaluation and the Genie phrasing sheet; any new question that Genie gets wrong is added to the Genie space as a certified example | Data team | Consistency stays at 100% |

**What we track after go-live:** time to produce each pack; number of questions answered in Board meetings; share of
answers Green / Amber / Red; open data issues per owner; review-queue age; agent and Genie consistency scores.
