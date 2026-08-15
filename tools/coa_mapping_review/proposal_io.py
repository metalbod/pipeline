"""Parses a coa-mapper proposal (pasted text or an uploaded file) into a validated DataFrame.

v1 deliberately does not call the coa-mapper subagent itself (see the plan's rationale) -- a
human runs coa-mapper in chat, asks it to emit its proposal table as CSV, and pastes/uploads that
here. This module's only job is turning that raw CSV into a polars DataFrame that's passed the
CoaMappingProposalSchema contract before it's ever shown in the review table.
"""

import io

import pandera.errors
import polars as pl

from data_quality.pandera_schemas.coa_mapping_proposal_schema import CoaMappingProposalSchema

EXPECTED_COLUMNS = [
    "local_account_code",
    "local_account_name",
    "proposed_group_standard_account_code",
    "confidence",
    "rationale",
]


class ProposalParseError(Exception):
    """Raised when pasted/uploaded proposal text isn't valid CSV or fails the Pandera contract.
    Caught by app.py and shown as an inline error -- malformed input is rejected up front, never
    silently coerced into the review table."""


def parse_proposal_csv(csv_text: str) -> pl.DataFrame:
    if not csv_text or not csv_text.strip():
        raise ProposalParseError("No proposal text provided.")

    try:
        df = pl.read_csv(io.StringIO(csv_text), schema_overrides={col: pl.Utf8 for col in EXPECTED_COLUMNS})
    except Exception as exc:
        raise ProposalParseError(f"Could not parse as CSV: {exc}") from exc

    missing = [col for col in EXPECTED_COLUMNS if col not in df.columns]
    if missing:
        raise ProposalParseError(
            f"Missing expected column(s): {', '.join(missing)}. "
            f"Expected: {', '.join(EXPECTED_COLUMNS)}."
        )

    df = df.select(EXPECTED_COLUMNS)

    try:
        CoaMappingProposalSchema.validate(df)
    except pandera.errors.SchemaError as exc:
        raise ProposalParseError(f"Proposal failed validation: {exc}") from exc

    return df
