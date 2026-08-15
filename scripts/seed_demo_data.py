"""One-time synthetic-data backfill: 12 entities x 12 months of realistic financial activity,
written directly to Bronze via write_bronze()/archive_raw_file_upload() -- bypassing the
per-file/per-API ceremony of the live connectors for this bulk historical load, but reusing the
same Bronze schemas and _source_system tagging so lineage stays honest. Same scripts/
convention as xero_oauth_bootstrap.py. Not a live connector -- a demo-data generator.

Reproducible: fixed random seed means re-running produces identical numbers.

Design note (see Phase 5 plan): fct_balance.sql's closing_balance is a *cumulative* running
total since inception, computed via a window function -- so Assets = Liabilities + Equity holds
automatically at every period for every entity as long as every individual journal entry is
double-entry balanced. This script only needs to emit well-formed balanced entries; it doesn't
need to carry forward opening balances itself.

Run via: python scripts/seed_demo_data.py
"""

import random
import sys
import uuid
from datetime import date, datetime, timezone

import pyarrow as pa

from ingestion.bronze_schemas import (
    ACCOUNTS_SCHEMA,
    AGING_SCHEMA,
    BUDGET_SCHEMA,
    JOURNAL_LINES_SCHEMA,
    PIPELINE_SNAPSHOT_SCHEMA,
)
from ingestion.delta_writer import new_batch_id, write_bronze

random.seed(42)

# 2025-08 through 2026-07 (12 months) -- extends the existing single period backward.
PERIODS = []
_y, _m = 2025, 8
for _ in range(12):
    PERIODS.append((_y, _m))
    _m += 1
    if _m > 12:
        _m = 1
        _y += 1

PIPELINE_STAGES = ["Prospecting", "Qualification", "Proposal", "ClosedWon"]

# entity_id -> (source_system, cash_code, currency, base_revenue, growth_rate, margin_pct,
# opex_pct, loan_multiplier). loan_multiplier scales the one-time loan principal against the
# entity's own projected 12-month net income, spreading debt-to-equity ratios across a
# realistic range relative to the 2.0x covenant threshold -- some comfortably under, one or two
# close to or past it.
ENTITIES = {
    "MY-PARENT":  ("xero",        "090",  "MYR", 40000, 0.015, 0.60, 0.15, 1.2),
    "SG-SUB":     ("file_upload", "1000", "SGD", 15000, 0.020, 0.65, 0.18, 0.8),
    "MY-SUB-01":  ("file_upload", "1000", "MYR", 22000, 0.010, 0.58, 0.16, 0.6),
    "MY-SUB-02":  ("file_upload", "1000", "MYR", 18000, 0.025, 0.62, 0.14, 1.5),
    "MY-SUB-03":  ("file_upload", "1000", "MYR", 12000, 0.005, 0.70, 0.20, 0.9),
    "MY-SUB-04":  ("file_upload", "1000", "MYR", 30000, 0.018, 0.55, 0.12, 2.4),
    "MY-SUB-05":  ("file_upload", "1000", "MYR", 9000,  0.008, 0.68, 0.22, 0.4),
    "MY-SUB-06":  ("file_upload", "1000", "MYR", 16000, 0.012, 0.60, 0.17, 1.1),
    "MY-SUB-07":  ("file_upload", "1000", "MYR", 20000, 0.022, 0.72, 0.19, 0.7),
    "MY-SUB-08":  ("file_upload", "1000", "MYR", 11000, 0.006, 0.63, 0.15, 0.5),
    "SG-SUB-02":  ("file_upload", "1000", "SGD", 25000, 0.017, 0.57, 0.13, 1.8),
    "SG-SUB-03":  ("file_upload", "1000", "SGD", 8000,  0.009, 0.75, 0.21, 0.3),
}

# MY-PARENT and SG-SUB already have real 2026-07 data from earlier sessions (Xero fixtures /
# file uploads) -- generating that same period again would double-count revenue/COGS/etc for
# those two entities. Everyone else has zero prior data, so they get the full 12 months.
ENTITIES_WITH_EXISTING_JULY_DATA = {"MY-PARENT", "SG-SUB"}

AP_CODE = "800"
AR_CODE = "610"
SALES_CODE = "200"
OPEX_CODE = "400"
COGS_CODE = "500"
LOAN_CODE = "2100"

COLLECT_PCT = 0.90  # fraction of this period's AR/AP settled within the period
PAY_PCT = 0.90


def _month_days(year: int, month: int) -> int:
    if month == 12:
        nxt = date(year + 1, 1, 1)
    else:
        nxt = date(year, month + 1, 1)
    return (nxt - date(year, month, 1)).days


def _project_financials(base_revenue, growth_rate, margin_pct, opex_pct, periods):
    """Per-entity revenue/COGS/opex trajectory, computed once so the loan principal (sized off
    projected equity) can be picked before emitting any journal entries."""
    trajectory = []
    for i, (y, m) in enumerate(periods):
        noise = random.uniform(0.92, 1.08)
        revenue = round(base_revenue * ((1 + growth_rate) ** i) * noise, 2)
        cogs = round(revenue * margin_pct * random.uniform(0.97, 1.03), 2)
        opex = round(base_revenue * opex_pct * random.uniform(0.90, 1.10), 2)
        trajectory.append({"year": y, "month": m, "revenue": revenue, "cogs": cogs, "opex": opex})
    return trajectory


def _journal_lines_rows(entity_id, source_system, cash_code, currency, trajectory, loan_multiplier, skip_loan=False):
    now = datetime.now(timezone.utc)
    rows = []

    def emit(journal_id, line_no, account_code, account_name, debit, credit, posted_at, description):
        rows.append({
            "_ingested_at": now,
            "_source_system": source_system,
            "_source_file_or_endpoint": "seed_demo_data.py",
            "_batch_id": batch_id,
            "entity_id": entity_id,
            "source_record_id": f"{entity_id}:{journal_id}:{line_no}",
            "journal_id": journal_id,
            "line_no": line_no,
            "account_code": account_code,
            "account_name": account_name,
            "debit_amount": round(debit, 2),
            "credit_amount": round(credit, 2),
            "currency": currency,
            "description": description,
            "posted_at": posted_at,
            "source_updated_at": now,
        })

    batch_id = new_batch_id()

    total_net_income = sum(t["revenue"] - t["cogs"] - t["opex"] for t in trajectory)
    loan_principal = round(max(total_net_income, 1000) * loan_multiplier, 2)

    for i, t in enumerate(trajectory):
        y, m = t["year"], t["month"]
        posted_mid = date(y, m, min(15, _month_days(y, m)))
        posted_early = date(y, m, min(5, _month_days(y, m)))
        posted_late = date(y, m, min(25, _month_days(y, m)))
        revenue, cogs, opex = t["revenue"], t["cogs"], t["opex"]

        je = f"JE-{entity_id}-{y}{m:02d}-SALES"
        emit(je, 0, AR_CODE, "Accounts Receivable", revenue, 0, posted_early, "Sales revenue")
        emit(je, 1, SALES_CODE, "Sales", 0, revenue, posted_early, "Sales revenue")

        collect = round(revenue * COLLECT_PCT, 2)
        je = f"JE-{entity_id}-{y}{m:02d}-COLLECT"
        emit(je, 0, cash_code, "Cash/Bank", collect, 0, posted_mid, "Customer collections")
        emit(je, 1, AR_CODE, "Accounts Receivable", 0, collect, posted_mid, "Customer collections")

        je = f"JE-{entity_id}-{y}{m:02d}-COGS"
        emit(je, 0, COGS_CODE, "Cost of Goods Sold", cogs, 0, posted_early, "Cost of goods sold")
        emit(je, 1, AP_CODE, "Accounts Payable", 0, cogs, posted_early, "Cost of goods sold")

        je = f"JE-{entity_id}-{y}{m:02d}-OPEX"
        emit(je, 0, OPEX_CODE, "Office Expenses", opex, 0, posted_mid, "Operating expenses")
        emit(je, 1, AP_CODE, "Accounts Payable", 0, opex, posted_mid, "Operating expenses")

        pay = round((cogs + opex) * PAY_PCT, 2)
        je = f"JE-{entity_id}-{y}{m:02d}-PAYAP"
        emit(je, 0, AP_CODE, "Accounts Payable", pay, 0, posted_late, "Vendor payments")
        emit(je, 1, cash_code, "Cash/Bank", 0, pay, posted_late, "Vendor payments")

        if i == 0 and not skip_loan:
            je = f"JE-{entity_id}-{y}{m:02d}-LOAN"
            emit(je, 0, cash_code, "Cash/Bank", loan_principal, 0, posted_early, "Term loan drawdown")
            emit(je, 1, LOAN_CODE, "External Bank Loans", 0, loan_principal, posted_early, "Term loan drawdown")

    return rows


def _accounts_rows(entity_id, source_system, cash_code):
    now = datetime.now(timezone.utc)
    local_accounts = [
        (cash_code, "Cash/Bank"),
        (AR_CODE, "Accounts Receivable"),
        (AP_CODE, "Accounts Payable"),
        (SALES_CODE, "Sales"),
        (OPEX_CODE, "Office Expenses"),
        (COGS_CODE, "Cost of Goods Sold"),
        (LOAN_CODE, "External Bank Loans"),
    ]
    return [
        {
            "_ingested_at": now,
            "_source_system": source_system,
            "_source_file_or_endpoint": "seed_demo_data.py",
            "_batch_id": new_batch_id(),
            "entity_id": entity_id,
            "local_account_code": code,
            "local_account_name": name,
            "local_account_type": None,
        }
        for code, name in local_accounts
    ]


def _budget_rows(entity_id, source_system, currency, trajectory):
    now = datetime.now(timezone.utc)
    rows = []
    batch_id = new_batch_id()
    for t in trajectory:
        period = f"{t['year']:04d}-{t['month']:02d}"
        for code, name, actual in [
            (SALES_CODE, "Sales", t["revenue"]),
            (COGS_CODE, "Cost of Goods Sold", t["cogs"]),
            (OPEX_CODE, "Office Expenses", t["opex"]),
        ]:
            budgeted = round(actual * random.uniform(0.85, 1.15), 2)
            rows.append({
                "_ingested_at": now,
                "_source_system": source_system,
                "_source_file_or_endpoint": "seed_demo_data.py",
                "_batch_id": batch_id,
                "entity_id": entity_id,
                "account_code": code,
                "account_name": name,
                "period": period,
                "budgeted_amount": budgeted,
                "currency": currency,
            })
    return rows


def _pipeline_rows(entity_id, source_system, currency, base_revenue, periods):
    now = datetime.now(timezone.utc)
    rows = []
    batch_id = new_batch_id()
    for i, (y, m) in enumerate(periods):
        period = f"{y:04d}-{m:02d}"
        for stage in PIPELINE_STAGES:
            stage_factor = {"Prospecting": 0.8, "Qualification": 0.5, "Proposal": 0.3, "ClosedWon": 0.15}[stage]
            noise = random.uniform(0.85, 1.15)
            tcv = round(base_revenue * stage_factor * noise * (1 + 0.01 * i), 2)
            deals = max(1, round(tcv / (base_revenue * 0.08)))
            rows.append({
                "_ingested_at": now,
                "_source_system": source_system,
                "_source_file_or_endpoint": "seed_demo_data.py",
                "_batch_id": batch_id,
                "entity_id": entity_id,
                "period": period,
                "pipeline_stage": stage,
                "deal_count": deals,
                "total_contract_value": tcv,
                "currency": currency,
            })
    return rows


def _aging_rows(entity_id, source_system, currency, base_revenue, today):
    """One current snapshot, not 12 months -- aging is point-in-time, not a historical series
    (see stg_ar_aging.sql's own design)."""
    now = datetime.now(timezone.utc)
    ar_rows, ap_rows = [], []
    ar_batch, ap_batch = new_batch_id(), new_batch_id()

    for i in range(random.randint(2, 3)):
        amount = round(base_revenue * random.uniform(0.05, 0.20), 2)
        days_ago = random.randint(5, 70)
        invoice_date = date(today.year, today.month, 1)
        due_offset = random.randint(-40, 30)
        ar_rows.append({
            "_ingested_at": now,
            "_source_system": source_system,
            "_source_file_or_endpoint": "seed_demo_data.py",
            "_batch_id": ar_batch,
            "entity_id": entity_id,
            "source_record_id": f"INV-{entity_id}-{i+1}",
            "contact_name": f"{entity_id} Customer {i+1}",
            "invoice_date": invoice_date,
            "due_date": date.fromordinal(today.toordinal() - days_ago + due_offset),
            "amount_outstanding": amount,
            "currency": currency,
        })

    for i in range(random.randint(2, 3)):
        amount = round(base_revenue * random.uniform(0.03, 0.12), 2)
        days_ago = random.randint(5, 60)
        invoice_date = date(today.year, today.month, 1)
        due_offset = random.randint(-30, 30)
        ap_rows.append({
            "_ingested_at": now,
            "_source_system": source_system,
            "_source_file_or_endpoint": "seed_demo_data.py",
            "_batch_id": ap_batch,
            "entity_id": entity_id,
            "source_record_id": f"BILL-{entity_id}-{i+1}",
            "contact_name": f"{entity_id} Vendor {i+1}",
            "invoice_date": invoice_date,
            "due_date": date.fromordinal(today.toordinal() - days_ago + due_offset),
            "amount_outstanding": amount,
            "currency": currency,
        })

    return ar_rows, ap_rows


def main():
    today = date(2026, 8, 15)
    all_journal_lines, all_accounts, all_budget, all_pipeline = [], [], [], []
    all_ar, all_ap = [], []

    for entity_id, (source_system, cash_code, currency, base_revenue, growth_rate, margin_pct, opex_pct, loan_mult) in ENTITIES.items():
        periods = PERIODS[:-1] if entity_id in ENTITIES_WITH_EXISTING_JULY_DATA else PERIODS
        trajectory = _project_financials(base_revenue, growth_rate, margin_pct, opex_pct, periods)
        all_journal_lines.extend(_journal_lines_rows(entity_id, source_system, cash_code, currency, trajectory, loan_mult))
        all_accounts.extend(_accounts_rows(entity_id, source_system, cash_code))
        all_budget.extend(_budget_rows(entity_id, source_system, currency, trajectory))
        all_pipeline.extend(_pipeline_rows(entity_id, source_system, currency, base_revenue, periods))
        ar, ap = _aging_rows(entity_id, source_system, currency, base_revenue, today)
        all_ar.extend(ar)
        all_ap.extend(ap)

    write_bronze("journal_lines", pa.Table.from_pylist(all_journal_lines, schema=JOURNAL_LINES_SCHEMA))
    write_bronze("accounts", pa.Table.from_pylist(all_accounts, schema=ACCOUNTS_SCHEMA))
    write_bronze("budget", pa.Table.from_pylist(all_budget, schema=BUDGET_SCHEMA))
    write_bronze("pipeline_snapshot", pa.Table.from_pylist(all_pipeline, schema=PIPELINE_SNAPSHOT_SCHEMA))
    write_bronze("ar_aging", pa.Table.from_pylist(all_ar, schema=AGING_SCHEMA))
    write_bronze("ap_aging", pa.Table.from_pylist(all_ap, schema=AGING_SCHEMA))

    print(f"journal_lines: {len(all_journal_lines)} rows")
    print(f"accounts: {len(all_accounts)} rows")
    print(f"budget: {len(all_budget)} rows")
    print(f"pipeline_snapshot: {len(all_pipeline)} rows")
    print(f"ar_aging: {len(all_ar)} rows")
    print(f"ap_aging: {len(all_ap)} rows")


def topup_july():
    """One-off, additive correction -- not part of main()'s bulk backfill, and doesn't touch
    anything main() already wrote.

    MY-PARENT and SG-SUB were carved out of main()'s 12-month backfill for 2026-07
    (ENTITIES_WITH_EXISTING_JULY_DATA) because they already had real 2026-07 data from the
    original Phase 1 pilot fixtures. That carve-out left July at the original pilot's tiny
    scale ($1,000/$1,500 revenue) while these two entities' other 11 months carry the full
    synthetic trajectory (tens of thousands/month) -- and since fct_balance's closing_balance
    is a *cumulative* running total, July's AR balance still reflects 11 months of
    trajectory-scale growth. Dividing that balance by July's tiny revenue in rpt_dso_dpo
    produced a nonsensical days-outstanding figure (MY-PARENT: 1,476.7 days).

    Bronze is append-only, so the original pilot fixture can't be removed or rescaled --
    this appends a trajectory-scaled July on top of it instead. The original fixture's
    $1-3k becomes immaterial next to the ~$50k trajectory-scale entry, which is enough to
    bring AR growth and revenue back into the same scale for July.

    Run via: python scripts/seed_demo_data.py --topup-july
    """
    all_journal_lines = []
    for entity_id in ("MY-PARENT", "SG-SUB"):
        source_system, cash_code, currency, base_revenue, growth_rate, margin_pct, opex_pct, _loan_mult = ENTITIES[entity_id]
        trajectory = _project_financials(base_revenue, growth_rate, margin_pct, opex_pct, PERIODS)
        july = trajectory[-1:]  # full 12-period trajectory computed so July's growth exponent
        # (i=11) is correct; only the last entry is actually emitted.
        rows = _journal_lines_rows(entity_id, source_system, cash_code, currency, july, loan_multiplier=0, skip_loan=True)
        all_journal_lines.extend(rows)
        print(f"{entity_id}: topping up July 2026 with {len(rows)} journal lines "
              f"(revenue={july[0]['revenue']:.2f}, cogs={july[0]['cogs']:.2f}, opex={july[0]['opex']:.2f})")

    write_bronze("journal_lines", pa.Table.from_pylist(all_journal_lines, schema=JOURNAL_LINES_SCHEMA))
    print(f"journal_lines: {len(all_journal_lines)} rows appended")


if __name__ == "__main__":
    if "--topup-july" in sys.argv:
        topup_july()
    else:
        main()
