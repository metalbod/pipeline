"""Pandera contract for the sales-pipeline Excel/CSV upload template. Finance-entered estimate,
not live CRM data (see ingestion/file_connectors/pipeline_file_reader.py header) -- validated at
the ingestion boundary before anything is accepted into Bronze, same pattern as
journal_upload_schema.py.
"""

import polars as pl
import pandera.polars as pa
from pandera.typing.polars import Series

PIPELINE_STAGES = ["Prospecting", "Qualification", "Proposal", "Negotiation", "ClosedWon"]


class PipelineUploadSchema(pa.DataFrameModel):
    period: Series[str] = pa.Field(nullable=False)
    pipeline_stage: Series[str] = pa.Field(nullable=False, isin=PIPELINE_STAGES)
    deal_count: Series[int] = pa.Field(nullable=False, ge=0)
    total_contract_value: Series[float] = pa.Field(nullable=False, ge=0)
    currency: Series[str] = pa.Field(nullable=False, str_length={"min_value": 3, "max_value": 3})

    class Config:
        strict = True
