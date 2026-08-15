"""Pandera contract for the AR/AP aging Excel/CSV upload template (SG-SUB and future entities).
Shared by both ar_aging and ap_aging doctypes -- same shape either way, see
ingestion/file_connectors/aging_file_reader.py.
"""

import polars as pl
import pandera.polars as pa
from pandera.typing.polars import Series


class AgingUploadSchema(pa.DataFrameModel):
    invoice_id: Series[str] = pa.Field(nullable=False)
    contact_name: Series[str] = pa.Field(nullable=False)
    invoice_date: Series[pl.Date] = pa.Field(nullable=False)
    due_date: Series[pl.Date] = pa.Field(nullable=False)
    amount_outstanding: Series[float] = pa.Field(nullable=False, ge=0)
    currency: Series[str] = pa.Field(nullable=False, str_length={"min_value": 3, "max_value": 3})

    class Config:
        strict = True
