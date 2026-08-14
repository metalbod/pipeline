from contextlib import contextmanager

import dagster as dg

from ingestion.api_connectors.xero.client import build_xero_client


class XeroClientResource(dg.ConfigurableResource):
    """Wraps client.build_xero_client()'s OAuth2 handling as a Dagster resource.

    Raises XeroConfigError (a clear, propagated failure -- no silent no-op) if credentials or
    the bootstrapped token file are missing. Note: Xero refresh tokens are single-use: if
    xero_accounts_bronze and xero_journals_bronze both refresh concurrently in the same run,
    the second refresh could race the first's token rotation. Dagster's default in-process dev
    executor runs assets sequentially, so this isn't an issue locally; a multi-worker production
    executor would need a lock around the token file -- worth revisiting once live credentials
    and a real schedule are in play.
    """

    @contextmanager
    def get_client(self):
        client = build_xero_client()
        try:
            yield client
        finally:
            client.close()
