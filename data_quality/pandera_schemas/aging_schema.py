"""Pandera contract on the normalized AR/AP aging output (Xero's Aged*ByContact reports, and
SG-SUB's aging file uploads), before Bronze write -- shared by both since the two sources
converge on one schema (ingestion/bronze_schemas.py's AGING_SCHEMA)."""

import pandera.polars as pa
from pandera.typing.polars import Series


class AgingSchema(pa.DataFrameModel):
    entity_id: Series[str] = pa.Field(nullable=False)
    source_record_id: Series[str] = pa.Field(nullable=False)
    contact_name: Series[str] = pa.Field(nullable=False)
    amount_outstanding: Series[float] = pa.Field(nullable=False, ge=0)

    class Config:
        strict = False  # also carries _ingested_at/_source_*, invoice_date, due_date, currency
