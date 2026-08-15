"""Pandera contract on the normalized budget output (Xero's BudgetSummary report, and SG-SUB's
budget file uploads), before Bronze write -- shared by both sources."""

import pandera.polars as pa
from pandera.typing.polars import Series


class BudgetSchema(pa.DataFrameModel):
    entity_id: Series[str] = pa.Field(nullable=False)
    account_name: Series[str] = pa.Field(nullable=False)
    period: Series[str] = pa.Field(nullable=False)
    budgeted_amount: Series[float] = pa.Field(nullable=False)

    class Config:
        strict = False  # also carries _ingested_at/_source_*, account_code, currency
