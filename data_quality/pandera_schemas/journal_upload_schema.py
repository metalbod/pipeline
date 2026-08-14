"""Pandera contract for the journal-entry Excel/CSV upload template (SG-SUB and future
entities). Validated at the ingestion boundary before anything is accepted into Bronze --
ARCHITECTURE.md §5: validate against the expected template, quarantine + alert on failure,
never silently drop rows. Aggregate double-entry balance (sum(debit) == sum(credit) per
journal_id) is enforced downstream as a dbt test, not here -- this schema is row-level shape.
"""

import polars as pl
import pandera.polars as pa
from pandera.typing.polars import Series


class JournalUploadSchema(pa.DataFrameModel):
    journal_id: Series[str] = pa.Field(nullable=False)
    line_no: Series[int] = pa.Field(nullable=False, ge=0)
    account_code: Series[str] = pa.Field(nullable=False)
    account_name: Series[str] = pa.Field(nullable=False)
    debit_amount: Series[float] = pa.Field(nullable=False, ge=0)
    credit_amount: Series[float] = pa.Field(nullable=False, ge=0)
    currency: Series[str] = pa.Field(nullable=False, str_length={"min_value": 3, "max_value": 3})
    description: Series[str] = pa.Field(nullable=True)
    posted_at: Series[pl.Date] = pa.Field(nullable=False)

    @pa.dataframe_check
    def exactly_one_amount_nonzero(cls, data) -> pl.LazyFrame:
        """Each line is either a debit or a credit, never both, never neither."""
        df = data.lazyframe
        return df.select(
            (
                (pl.col("debit_amount") > 0).cast(pl.Int8)
                + (pl.col("credit_amount") > 0).cast(pl.Int8)
            )
            == 1
        )

    class Config:
        strict = True
