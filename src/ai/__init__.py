"""MARI — AI cluster package (rebuild of Task 65-67 after Task 69 rollback).

Vendor-neutral AI layer: optional, honest, credentials outside source code.
READ ONLY | PAPER ONLY | NO LIVE ORDERS
"""

from src.ai.config import AIProviderConfig, load_provider_config, load_vault_slot, mask_secret
from src.ai.provider import (
    AIResponse,
    AIRole,
    AIStatus,
    role_system_prompt,
)

__all__ = [
    "AIProviderConfig",
    "load_provider_config",
    "load_vault_slot",
    "mask_secret",
    "AIResponse",
    "AIRole",
    "AIStatus",
    "role_system_prompt",
]
