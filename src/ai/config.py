"""MARI — AI provider configuration loader (L-layer search paths).

Vault first (dashboard token vault, canonical) -> legacy -> L4 restore layer.
Missing/unreadable config is NOT an error: AI is an optional layer and callers
must degrade gracefully (AIStatus.NOT_CONFIGURED).
Credentials never live in source code; files are owner-only (0600).
READ ONLY | PAPER ONLY | NO LIVE ORDERS
"""

import json
import os
from dataclasses import dataclass
from typing import Optional

ENV_CONFIG_PATH = "MARI_AI_CONFIG"
VAULT_PATH = "/home/z/my-project/data/vault-private/cloudflare.json"
PRIMARY_PATH = "/home/z/my-project/data/cloudflare-config.json"
RESTORE_PATH = "/tmp/my-project/data/cloudflare-config.json"

# Vault first (dashboard token page, canonical) -> legacy -> L4 restore layer
SEARCH_PATHS = (VAULT_PATH, PRIMARY_PATH, RESTORE_PATH)


def mask_secret(value: Optional[str], keep: int = 4) -> str:
    """Masked preview safe for logs/reports: cfut_abc123...3389."""
    if not value:
        return ""
    if len(value) <= 9:
        return "***"
    return f"{value[:5]}...{value[-keep:]}"


@dataclass(frozen=True)
class AIProviderConfig:
    """Vendor-neutral credential holder. api_token stays private here."""

    provider: str = "cloudflare"
    api_token: Optional[str] = None
    account_id: Optional[str] = None
    model: Optional[str] = None
    config_path: Optional[str] = None
    found_via: Optional[str] = None

    @property
    def is_configured(self) -> bool:
        return bool(self.api_token)

    @property
    def token_masked(self) -> str:
        return mask_secret(self.api_token)


def _read_json(path: str) -> dict:
    # Defensive hardening: config must be owner-only.
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass
    with open(path, "r", encoding="utf-8") as fh:
        data = json.load(fh)
    return data if isinstance(data, dict) else {}


def load_provider_config(
    search_paths: Optional[tuple] = None,
    provider: str = "cloudflare",
) -> AIProviderConfig:
    """Load provider config from env override or the L-layer search paths.

    Missing/unreadable config is NOT an error: AI is an optional layer and
    callers must degrade gracefully (AIStatus.NOT_CONFIGURED).
    """
    paths = list(search_paths or ())
    env_path = os.environ.get(ENV_CONFIG_PATH)
    if env_path:
        paths.insert(0, env_path)
    if not paths:
        paths = list(SEARCH_PATHS)

    for path in paths:
        if not path or not os.path.isfile(path):
            continue
        try:
            data = _read_json(path)
        except (OSError, ValueError):
            continue
        if data.get("provider") and data.get("provider") != provider:
            continue
        token = data.get("api_token") or data.get("token")
        return AIProviderConfig(
            provider=provider,
            api_token=str(token) if token else None,
            account_id=data.get("account_id") or data.get("accountId") or None,
            model=data.get("model") or None,
            config_path=path,
            found_via=(env_path if path == env_path else path),
        )
    return AIProviderConfig(provider=provider)


VAULT_DIR = "/home/z/my-project/data/vault-private"
VAULT_L4_DIR = "/tmp/my-project/data/vault-private"


def load_vault_slot(slot: str) -> AIProviderConfig:
    """Load a dashboard-vault slot (cloudflare/openai/gemini/deepseek).

    Vault files are written by the MARI dashboard token vault (chmod 600,
    gitignored) with keys {token, accountId, ...}. Missing file = NOT
    configured (optional layer, graceful).
    """
    for base in (VAULT_DIR, VAULT_L4_DIR):
        path = os.path.join(base, f"{slot}.json")
        if not os.path.isfile(path):
            continue
        try:
            data = _read_json(path)
        except (OSError, ValueError):
            continue
        token = data.get("token")
        if not token:
            continue
        return AIProviderConfig(
            provider=slot,
            api_token=str(token),
            account_id=data.get("accountId") or None,
            model=data.get("model") or None,
            config_path=path,
            found_via=base,
        )
    return AIProviderConfig(provider=slot)
