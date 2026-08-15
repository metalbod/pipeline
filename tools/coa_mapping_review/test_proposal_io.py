import pytest

from tools.coa_mapping_review.proposal_io import ProposalParseError, parse_proposal_csv

VALID_CSV = (
    "local_account_code,local_account_name,proposed_group_standard_account_code,confidence,rationale\n"
    "610,Accounts Receivable,GS-1100,high,Exact name match to group-standard AR account.\n"
    "999,Mystery Suspense Account,,low,No clear group-standard equivalent found.\n"
)


def test_parse_proposal_csv_happy_path():
    df = parse_proposal_csv(VALID_CSV)
    assert df.height == 2
    assert df["local_account_code"].to_list() == ["610", "999"]
    assert df["confidence"].to_list() == ["high", "low"]


def test_parse_proposal_csv_allows_blank_proposed_code_for_low_confidence():
    df = parse_proposal_csv(VALID_CSV)
    assert df["proposed_group_standard_account_code"].to_list()[1] in (None, "")


def test_parse_proposal_csv_empty_input():
    with pytest.raises(ProposalParseError, match="No proposal text"):
        parse_proposal_csv("")


def test_parse_proposal_csv_missing_column():
    bad_csv = "local_account_code,local_account_name\n610,Accounts Receivable\n"
    with pytest.raises(ProposalParseError, match="Missing expected column"):
        parse_proposal_csv(bad_csv)


def test_parse_proposal_csv_invalid_confidence():
    bad_csv = (
        "local_account_code,local_account_name,proposed_group_standard_account_code,confidence,rationale\n"
        "610,Accounts Receivable,GS-1100,super-confident,not a real confidence level\n"
    )
    with pytest.raises(ProposalParseError, match="failed validation"):
        parse_proposal_csv(bad_csv)


def test_parse_proposal_csv_not_csv():
    with pytest.raises(ProposalParseError):
        parse_proposal_csv("this is not csv at all, just prose")
