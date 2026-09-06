"""Resolves a connector's config_reference to a real secret value.

Mirrors the config_reference contract already used by ProviderModel
(app/routers/v2_governance.py) and the shadow-mode artifact loader
(app/services/experiments/shadow.py): the value must name where a secret
lives, never contain the secret itself. Only ``env:`` is actually
implemented — ``secret-manager:`` and ``file:`` are recognised prefixes
that honestly report themselves as not implemented in this deployment
rather than silently failing or pretending to work, and ``none:`` means
the connector is intentionally left unconfigured."""
from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass
class ResolvedSecret:
    value: str | None
    reason: str | None  # populated whenever value is None


def resolve_config_reference(config_reference: str | None) -> ResolvedSecret:
    if not config_reference:
        return ResolvedSecret(None, "No config_reference is set for this connector")
    if config_reference.startswith("none:"):
        return ResolvedSecret(None, "This connector is intentionally left unconfigured (none: reference)")
    if config_reference.startswith("env:"):
        var_name = config_reference[len("env:"):]
        value = os.environ.get(var_name)
        if not value:
            return ResolvedSecret(None, f"Environment variable '{var_name}' is not set in this deployment")
        return ResolvedSecret(value, None)
    if config_reference.startswith("secret-manager:"):
        return ResolvedSecret(None, "Secret-manager-backed config_reference resolution is not implemented in this deployment")
    if config_reference.startswith("file:"):
        return ResolvedSecret(None, "File-backed config_reference resolution is not implemented for connectors in this deployment")
    return ResolvedSecret(None, f"Unrecognised config_reference prefix: '{config_reference}'")
