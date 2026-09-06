"""Allowlisted connector-provider registry. Only providers listed in
VERIFIERS have a real, network-capable implementation; every other
provider row that already exists in the integrations table (email,
microsoft_teams, github, jira, servicenow, webhook) honestly reports
itself as not yet implemented rather than being silently accepted or
faked as working."""
from app.services.connectors.slack_webhook import ConnectorVerifyResult, verify as verify_slack

VERIFIERS = {
    "slack": verify_slack,
}


async def verify_connector(provider: str, config_reference: str | None) -> ConnectorVerifyResult:
    verifier = VERIFIERS.get(provider)
    if verifier is None:
        return ConnectorVerifyResult(False, f"Verification for provider '{provider}' is not implemented in this deployment")
    return await verifier(config_reference)
