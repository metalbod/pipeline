"""Pandera contract for the budget Excel/CSV upload template (SG-SUB and future entities). See
ingestion/file_connectors/budget_file_reader.py.
"""

import polars as pl
import pandera.polars as pa
from pandera.typing.polars import Series


class BudgetUploadSchema(pa.DataFrameModel):
    account_code: Series[str] = pa.Field(nullable=False)
    account_name: Series[str] = pa.Field(nullable=False)
    period: Series[str] = pa.Field(nullable=False)
    budgeted_amount: Series[float] = pa.Field(nullable=False)
    currency: Series[str] = pa.Field(nullable=False, str_length={"min_value": 3, "max_value": 3})

    class Config:
        strict = True
