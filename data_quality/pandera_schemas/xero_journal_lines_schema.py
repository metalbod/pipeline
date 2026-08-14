"""Pandera contract on the Xero connector's normalized journal-lines output, before Bronze
write. Per CLAUDE.md: every ingestion connector needs a Pandera schema. Mirrors
journal_upload_schema.py's row-level rules so both sources are held to the same shape before
they converge in Bronze (ARCHITECTURE.md §5)."""

import polars as pl
import pandera.polars as pa
from pandera.typing.polars import Series


class XeroJournalLinesSchema(pa.DataFrameModel):
    entity_id: Series[str] = pa.Field(nullable=False)
    source_record_id: Series[str] = pa.Field(nullable=False)
    journal_id: Series[str] = pa.Field(nullable=False)
    line_no: Series[int] = pa.Field(nullable=False, ge=0)
    account_code: Series[str] = pa.Field(nullable=False)
    account_name: Series[str] = pa.Field(nullable=False)
    debit_amount: Series[float] = pa.Field(nullable=False, ge=0)
    credit_amount: Series[float] = pa.Field(nullable=False, ge=0)
    posted_at: Series[pl.Date] = pa.Field(nullable=False)

    @pa.dataframe_check
    def exactly_one_amount_nonzero(cls, data) -> pl.LazyFrame:
        df = data.lazyframe
        return df.select(
            (
                (pl.col("debit_amount") > 0).cast(pl.Int8)
                + (pl.col("credit_amount") > 0).cast(pl.Int8)
            )
            == 1
        )

    class Config:
        strict = False  # normalized output also carries _ingested_at/_source_*/currency/description
