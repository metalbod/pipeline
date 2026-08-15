"""Pandera contract for a coa-mapper proposal pasted/uploaded into the COA mapping review UI
(tools/coa_mapping_review). This validates the *proposal* shape only -- the coa-mapper subagent's
own output columns (see .claude/agents/coa-mapper.md) -- not the governed seed_coa_mapping.csv
shape it eventually becomes after human review and write_path.py appends it.
"""

import pandera.polars as pa
from pandera.typing.polars import Series

CONFIDENCE_LEVELS = ["high", "medium", "low"]


class CoaMappingProposalSchema(pa.DataFrameModel):
    local_account_code: Series[str] = pa.Field(nullable=False)
    local_account_name: Series[str] = pa.Field(nullable=False)
    proposed_group_standard_account_code: Series[str] = pa.Field(nullable=True)
    confidence: Series[str] = pa.Field(nullable=False, isin=CONFIDENCE_LEVELS)
    rationale: Series[str] = pa.Field(nullable=True)

    class Config:
        strict = True
