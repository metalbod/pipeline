"""Pandera contract on the Xero connector's normalized Accounts output, before Bronze write.
Per CLAUDE.md: every ingestion connector needs a Pandera schema."""

import pandera.polars as pa
from pandera.typing.polars import Series


class XeroAccountsSchema(pa.DataFrameModel):
    entity_id: Series[str] = pa.Field(nullable=False)
    local_account_code: Series[str] = pa.Field(nullable=False)
    local_account_name: Series[str] = pa.Field(nullable=False)
    local_account_type: Series[str] = pa.Field(nullable=True)

    class Config:
        strict = False  # normalized output also carries _ingested_at/_source_* metadata columns
