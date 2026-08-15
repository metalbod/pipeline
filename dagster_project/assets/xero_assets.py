import dagster as dg

from dagster_project.resources import XeroClientResource
from ingestion.api_connectors.xero import ingest


@dg.asset(group_name="bronze_xero", description="Xero GET /Accounts (MY-PARENT local COA) -> Bronze")
def xero_accounts_bronze(context: dg.AssetExecutionContext, xero: XeroClientResource) -> dg.MaterializeResult:
    with xero.get_client() as client:
        result = ingest.ingest_accounts(client)
    return dg.MaterializeResult(
        metadata={"row_count": result["row_count"], "batch_id": result["batch_id"], "path": result["path"]}
    )


@dg.asset(group_name="bronze_xero", description="Xero GET /Journals (MY-PARENT GL) -> Bronze")
def xero_journals_bronze(context: dg.AssetExecutionContext, xero: XeroClientResource) -> dg.MaterializeResult:
    with xero.get_client() as client:
        result = ingest.ingest_journals(client)
    return dg.MaterializeResult(
        metadata={"row_count": result["row_count"], "batch_id": result["batch_id"], "path": result["path"]}
    )


@dg.asset(
    group_name="bronze_xero",
    description="Xero GET /Reports/AgedReceivablesByContact (MY-PARENT) -> Bronze",
)
def xero_aged_receivables_bronze(
    context: dg.AssetExecutionContext, xero: XeroClientResource
) -> dg.MaterializeResult:
    with xero.get_client() as client:
        result = ingest.ingest_aged_receivables(client)
    return dg.MaterializeResult(
        metadata={"row_count": result["row_count"], "batch_id": result["batch_id"], "path": result["path"]}
    )


@dg.asset(
    group_name="bronze_xero",
    description="Xero GET /Reports/AgedPayablesByContact (MY-PARENT) -> Bronze",
)
def xero_aged_payables_bronze(
    context: dg.AssetExecutionContext, xero: XeroClientResource
) -> dg.MaterializeResult:
    with xero.get_client() as client:
        result = ingest.ingest_aged_payables(client)
    return dg.MaterializeResult(
        metadata={"row_count": result["row_count"], "batch_id": result["batch_id"], "path": result["path"]}
    )


@dg.asset(group_name="bronze_xero", description="Xero GET /Reports/BudgetSummary (MY-PARENT) -> Bronze")
def xero_budget_bronze(context: dg.AssetExecutionContext, xero: XeroClientResource) -> dg.MaterializeResult:
    with xero.get_client() as client:
        result = ingest.ingest_budget_summary(client)
    return dg.MaterializeResult(
        metadata={"row_count": result["row_count"], "batch_id": result["batch_id"], "path": result["path"]}
    )
