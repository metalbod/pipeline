import json
from pathlib import Path

import httpx
import respx

from ingestion.api_connectors.xero import connector, normalize

FIXTURES = Path(__file__).parent / "fixtures"
API_BASE = "https://api.xero.com/api.xro/2.0"


def _load_fixture(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text())


def _client() -> httpx.Client:
    return httpx.Client(base_url=API_BASE)


@respx.mock
def test_fetch_accounts():
    respx.get(f"{API_BASE}/Accounts").mock(
        return_value=httpx.Response(200, json=_load_fixture("accounts.json"))
    )
    with _client() as client:
        accounts = connector.fetch_accounts(client)
    assert len(accounts) == 6
    assert accounts[0]["Code"] == "090"


@respx.mock
def test_fetch_all_journals_stops_on_short_page():
    respx.get(f"{API_BASE}/Journals").mock(
        return_value=httpx.Response(200, json=_load_fixture("journals.json"))
    )
    with _client() as client:
        journals = connector.fetch_all_journals(client)
    assert len(journals) == 3
    assert journals[-1]["JournalNumber"] == 3


@respx.mock
def test_fetch_all_journals_pages_until_short_page():
    full_page = [dict(_load_fixture("journals.json")["Journals"][0]) for _ in range(100)]
    for i, j in enumerate(full_page):
        j["JournalNumber"] = i + 1
        j["JournalID"] = f"j-page1-{i}"

    short_page = _load_fixture("journals.json")["Journals"][:2]

    route = respx.get(f"{API_BASE}/Journals")
    route.side_effect = [
        httpx.Response(200, json={"Journals": full_page}),
        httpx.Response(200, json={"Journals": short_page}),
    ]

    with _client() as client:
        journals = connector.fetch_all_journals(client)

    assert len(journals) == 102
    assert route.call_count == 2


def test_normalize_accounts_shape():
    raw = _load_fixture("accounts.json")["Accounts"]
    table = normalize.normalize_accounts(raw, "MY-PARENT", "batch-1")
    assert table.num_rows == 6
    assert table.schema.names == [f.name for f in normalize.ACCOUNTS_SCHEMA]
    row = table.to_pylist()[0]
    assert row["entity_id"] == "MY-PARENT"
    assert row["local_account_code"] == "090"
    assert row["_source_system"] == "xero"


def test_normalize_journals_debit_credit_split_and_balances():
    raw = _load_fixture("journals.json")["Journals"]
    table = normalize.normalize_journals(raw, "MY-PARENT", "batch-1")
    rows = table.to_pylist()

    # 3 journals x 2 lines each
    assert len(rows) == 6

    # Debits and credits are split from Xero's signed NetAmount correctly.
    j1_lines = [r for r in rows if r["journal_id"] == "j1111111-0000-0000-0000-000000000001"]
    ar_line = next(r for r in j1_lines if r["account_code"] == "610")
    sales_line = next(r for r in j1_lines if r["account_code"] == "200")
    assert ar_line["debit_amount"] == 1000.0
    assert ar_line["credit_amount"] == 0.0
    assert sales_line["debit_amount"] == 0.0
    assert sales_line["credit_amount"] == 1000.0

    # Every journal balances: sum(debit) == sum(credit) per journal_id.
    by_journal: dict[str, list[dict]] = {}
    for r in rows:
        by_journal.setdefault(r["journal_id"], []).append(r)
    for journal_id, lines in by_journal.items():
        assert sum(l["debit_amount"] for l in lines) == sum(l["credit_amount"] for l in lines)


def test_xero_datetime_handles_dotnet_and_iso_formats():
    dotnet = normalize._xero_datetime("/Date(1755129600000+0000)/")
    iso = normalize._xero_datetime("2026-07-05T09:12:00")
    assert dotnet.year == 2025
    assert iso.year == 2026
