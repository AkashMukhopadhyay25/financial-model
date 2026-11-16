# Databricks notebook source
# MAGIC %md
# MAGIC # make_demo_months — synthetic monthly deliveries for testing and the demo
# MAGIC
# MAGIC We only have one real delivery (as of 2026-06-30). To show history, trends and a same-month correction, this notebook
# MAGIC writes **clearly synthetic** follow-on months into the landing zone, starting from the files in `data/`:
# MAGIC
# MAGIC | Folder | Content |
# MAGIC |---|---|
# MAGIC | `incoming/2026-06/` | The original delivery, unchanged |
# MAGIC | `incoming/2026-07/` … `incoming/2026-10/` | Each month evolves the previous one: disbursements, approvals, signings, Pending → Active, Active → Closed, new Pending projects, reviews, risk-rating moves and performance changes |
# MAGIC | `_demo_staging/2026-10/` | A **corrected** October file (step 2 below) |
# MAGIC
# MAGIC The story the months tell (so the trends have something to find):
# MAGIC - **Jul–Aug:** stress in Energy and Sub-Saharan Africa: Performing → Watchlist → Past Due, rating downgrades; few reviews, so overdue reviews pile up.
# MAGIC - **Sep:** a review drive on high-risk projects; deterioration slows.
# MAGIC - **Oct:** recoveries and growth (approvals, signings, first disbursements). The first October upload contains a
# MAGIC   **keying error**: 25 performing Energy projects marked Past Due. The corrected October file fixes it.
# MAGIC
# MAGIC Every month keeps the data consistent with the contracts (Dropped = not monitored, Pending = no disbursement,
# MAGIC disbursed ≤ approved, client IDs ↔ names unchanged), so all blocking checks still pass.
# MAGIC
# MAGIC **Step 1:** run with `step = generate`, then run `01_data/run_monthly_pipeline`.
# MAGIC **Step 2 (re-upload test):** run with `step = reupload_october` (copies the corrected file into `incoming/2026-10/`),
# MAGIC then run the pipeline again: only October is rebuilt.

# COMMAND ----------

# MAGIC %run ../../00_setup/00_config

# COMMAND ----------

import calendar  # noqa: E402
import csv  # noqa: E402
import random  # noqa: E402
import shutil  # noqa: E402
from datetime import date, timedelta  # noqa: E402

dbutils.widgets.dropdown("step", "generate", ["generate", "reupload_october"], "Step")  # noqa: F821
STEP = dbutils.widgets.get("step")  # noqa: F821
INCOMING = Path(LANDING_ROOT) / CFG["landing_zone"]["incoming"]
STAGING = Path(LANDING_ROOT) / "_demo_staging"
BASE_P = REPO_ROOT / "data" / "synthetic_ifc_projects_5000.csv"
BASE_M = REPO_ROOT / "data" / "synthetic_project_monitoring.csv"
BASE_MONTH = "2026-06"
MONTHS = ["2026-07", "2026-08", "2026-09", "2026-10"]
P_NAME, M_NAME = "synthetic_ifc_projects_{}.csv", "synthetic_project_monitoring_{}.csv"

# Column names in the source files
URL, NUM, STATUS, APPROVED, SIGNED, INVESTED = ("Project Url", "Project Number", "Status", "IFC Approval Date",
                                                "IFC Signed Date", "IFC Invested Date")
TOTAL, ASOF, BOARD, INDUSTRY, REGION = ("Total IFC investment as approved by Board(Million - USD)", "As of Date",
                                        "Projected Board Date", "Industry", "Region")
AMOUNTS = ["IFC investment for Risk Management(Million - USD)", "IFC investment for Guarantee(Million - USD)",
           "IFC investment for Loan(Million - USD)", "IFC investment for Equity(Million - USD)"]
RATING, DISB, PERF, DAYS = ("Internal Risk Rating", "IFC Disbursed Amount(Million - USD)", "Performance Status",
                            "Days Since Last Review")

# COMMAND ----------


def read(path):
    with open(path, newline="", encoding="utf-8-sig") as f:
        r = csv.DictReader(f)
        return r.fieldnames, list(r)


def write(path, header, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=header, lineterminator="\n")
        w.writeheader()
        w.writerows(rows)
    print(f"  wrote {path} ({len(rows)} rows)")


def month_end(label):
    y, m = int(label[:4]), int(label[5:])
    return date(y, m, calendar.monthrange(y, m)[1])


def day_in(label, rnd, not_before=None):
    """A random day in the month, not before `not_before` (ISO text) when given."""
    first, last = date(int(label[:4]), int(label[5:]), 1), month_end(label)
    lo = max(first, date.fromisoformat(not_before)) if not_before else first
    lo = min(lo, last)
    return (lo + timedelta(days=rnd.randint(0, (last - lo).days))).isoformat()


def f6(x):
    return f"{x:.6f}"


def evolve(projects, monitoring, label, rnd, next_id):
    """Advance the portfolio by one month. Returns (projects, monitoring, next_id); inputs are not modified."""
    projects = [dict(p) for p in projects]
    mon = {k: dict(v) for k, v in monitoring.items()}
    end = month_end(label).isoformat()
    ndays = month_end(label).day
    prev_cycle = max(p[ASOF] for p in projects)
    stress = label in ("2026-07", "2026-08")
    review_drive = label in ("2026-09", "2026-10")
    recovery = label == "2026-10"
    changed = set()

    for p in projects:
        url = p[URL]
        m = mon.get(url)
        st = p[STATUS]
        before = dict(p)
        if st == "Active" and m:
            # performance and rating
            perf, stressed = m[PERF], stress and (p[INDUSTRY] == "Energy" or p[REGION] == "Sub-Saharan Africa")
            if perf == "Performing" and rnd.random() < (0.07 if stressed else 0.012 if not recovery else 0.004):
                m[PERF] = "Watchlist"
            elif perf == "Watchlist" and rnd.random() < (0.15 if stressed else 0.03 if not recovery else 0.01):
                m[PERF] = "Past Due"
            elif perf == "Watchlist" and rnd.random() < (0.30 if recovery else 0.12 if review_drive else 0.04):
                m[PERF] = "Performing"
            elif perf == "Past Due" and rnd.random() < (0.12 if recovery else 0.03):
                m[PERF] = "Watchlist"
            r = int(m[RATING])
            if m[PERF] != perf and m[PERF] in ("Watchlist", "Past Due") and rnd.random() < 0.6:
                m[RATING] = str(min(6, r + 1))
            elif m[PERF] != perf and m[PERF] == "Performing" and rnd.random() < 0.5:
                m[RATING] = str(max(1, r - 1))
            # disbursements
            approved, disb = float(p[TOTAL]), float(m[DISB] or 0)
            if disb < approved - 0.01 and rnd.random() < 0.3:
                m[DISB] = f6(min(approved, disb + (approved - disb) * rnd.uniform(0.02, 0.08)))
            # Active -> Closed (a few long-running performing projects)
            if m[PERF] == "Performing" and p[INVESTED] and p[INVESTED] < "2019-01-01" and rnd.random() < 0.03:
                p[STATUS], m[PERF], m[DAYS] = "Closed", "Completed", ""
            if p != before or m != monitoring[url]:
                changed.add(url)
        elif st == "Pending" and m:
            if not p[APPROVED] and p[BOARD] and p[BOARD] <= end and rnd.random() < (0.25 if recovery else 0.12):
                p[APPROVED] = day_in(label, rnd, p[BOARD] if p[BOARD][:7] == label else None)
            elif p[APPROVED] and not p[SIGNED] and rnd.random() < (0.12 if recovery else 0.06):
                p[SIGNED] = day_in(label, rnd, p[APPROVED] if p[APPROVED][:7] == label else None)
            elif p[APPROVED] and p[SIGNED] and rnd.random() < (0.10 if recovery else 0.05):
                p[STATUS] = "Active"
                p[INVESTED] = day_in(label, rnd, p[SIGNED] if p[SIGNED][:7] == label else None)
                m[PERF], m[DISB] = "Performing", f6(float(p[TOTAL]) * rnd.uniform(0.1, 0.3))
            if p != before or m != monitoring[url]:
                changed.add(url)

        # reviews: every open (non-Closed) monitored project either gets reviewed or a month older
        if m and p[STATUS] != "Closed" and m[DAYS] != "":
            high = int(m[RATING]) >= 5
            p_review = (0.9 if high else 0.5) if review_drive else 0.25
            m[DAYS] = str(rnd.randint(1, ndays) if rnd.random() < p_review else int(m[DAYS]) + ndays)

        # refresh: rows of the last cycle, anything that changed, and 25% of older (outdated) rows
        if p[ASOF] == prev_cycle or url in changed or rnd.random() < 0.25:
            p[ASOF] = end
        if m:
            mon[url] = m

    # new Pending projects, copied from an existing Pending project (same client, so client IDs stay consistent)
    templates = [p for p in projects if p[STATUS] == "Pending" and p[URL] in mon and p["Project Description"]]
    for _ in range(rnd.randint(8, 14) + (6 if recovery else 0)):
        t = rnd.choice(templates)
        new = dict(t)
        new[URL] = f"https://ifc.example.org/project/{next_id}"
        new[NUM] = str(rnd.randint(1000, 9999))
        new["Project Name"] = t["Project Name"] + " II"
        new["Date Disclosed"] = day_in(label, rnd)
        new[BOARD] = (month_end(label) + timedelta(days=rnd.randint(45, 180))).isoformat()
        new[APPROVED] = new[SIGNED] = new[INVESTED] = ""
        scale = rnd.uniform(0.5, 1.5)
        amts = [float(t[a]) * scale for a in AMOUNTS]
        for a, v in zip(AMOUNTS, amts):
            new[a] = f6(v)
        new[TOTAL] = f6(sum(round(v, 6) for v in amts))
        new[ASOF] = end
        nm = dict(mon[t[URL]])
        nm.update({URL: new[URL], NUM: new[NUM], RATING: str(rnd.randint(2, 4)), DISB: "", PERF: "", DAYS: str(rnd.randint(1, ndays))})
        projects.append(new)
        mon[new[URL]] = nm
        next_id += 1
    return projects, mon, next_id


def with_keying_error(projects, monitoring, rnd):
    """October's first upload: 25 performing Energy projects wrongly keyed as Past Due."""
    mon = {k: dict(v) for k, v in monitoring.items()}
    energy = [p[URL] for p in projects if p[STATUS] == "Active" and p[INDUSTRY] == "Energy" and mon[p[URL]][PERF] == "Performing"]
    for url in rnd.sample(energy, 25):
        mon[url][PERF] = "Past Due"
    return mon

# COMMAND ----------

if STEP == "generate":
    hp, projects = read(BASE_P)
    hm, mon_rows = read(BASE_M)
    monitoring = {r[URL]: r for r in mon_rows}
    print(f"Base delivery: {len(projects)} projects, {len(monitoring)} monitoring rows (as of {max(p[ASOF] for p in projects)})")

    write(INCOMING / BASE_MONTH / P_NAME.format("5000"), hp, projects)
    write(INCOMING / BASE_MONTH / M_NAME.format(BASE_MONTH), hm, list(monitoring.values()))

    next_id = 1 + max(int(p[URL].rsplit("/", 1)[1]) for p in projects)
    for label in MONTHS:
        rnd = random.Random(f"ifc-demo-{label}")
        projects, monitoring, next_id = evolve(projects, monitoring, label, rnd, next_id)
        mon_out = [monitoring[p[URL]] for p in projects if p[URL] in monitoring and p[STATUS] != "Dropped"]
        if label == "2026-10":
            # the corrected file goes to staging; the first upload carries the keying error
            write(STAGING / label / M_NAME.format(label + "_corrected"), hm, mon_out)
            bad = with_keying_error(projects, monitoring, rnd)
            mon_out = [bad[p[URL]] for p in projects if p[URL] in bad and p[STATUS] != "Dropped"]
        write(INCOMING / label / P_NAME.format(label), hp, projects)
        write(INCOMING / label / M_NAME.format(label), hm, mon_out)
    print("\nNext: run 01_data/run_monthly_pipeline (same config_path).")

else:
    src = STAGING / "2026-10"
    files = sorted(src.glob("*.csv"))
    assert files, f"No corrected file in {src}. Run step = generate first."
    for f in files:
        dest = INCOMING / "2026-10" / f.name
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(str(f), str(dest))
        print(f"Re-upload: {f.name} -> {dest}")
    print("\nNext: run 01_data/run_monthly_pipeline again. Only 2026-10 is rebuilt; the earlier October upload is kept "
          "in Raw and marked superseded in ops_monthly_loads.")
