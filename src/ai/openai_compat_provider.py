"""MARI — OpenAI-compatible provider adapter (OpenAI / DeepSeek / Gemini endpoints).

Rebuild of Task 67 phase 6. Reads dashboard-vault slots; identical honest-status
semantics as the Cloudflare provider. Analysis-only output — never a signal.
READ ONLY | PAPER ONLY | NO LIVE ORDERS
"""

import json
from typing import Callable, Dict, Optional, Tuple

from src.ai.cloudflare_provider import Transport, default_transport
from src.ai.config import AIProviderConfig, load_vault_slot, mask_secret
from src.ai.provider import AIResponse, AIStatus, now_ms

OPENAI_COMPAT_ENDPOINTS: Dict[str, Dict[str, str]] = {
    "openai": {"base": "https://api.openai.com/v1", "model": "gpt-4o-mini", "label": "OpenAI"},
    "deepseek": {"base": "https://api.deepseek.com/v1", "model": "deepseek-chat", "label": "DeepSeek"},
    "gemini": {
        "base": "https://generativelanguage.googleapis.com/v1beta/openai",
        "model": "gemini-2.0-flash",
        "label": "Gemini",
    },
}


class OpenAICompatProvider:
    """One adapter for the OpenAI-compatible trio; transport injectable for tests."""

    def __init__(
        self,
        config: AIProviderConfig,
        transport: Optional[Transport] = None,
        timeout: float = 30.0,
        endpoint: Optional[Dict[str, str]] = None,
    ):
        if config.provider not in OPENAI_COMPAT_ENDPOINTS and endpoint is None:
            raise ValueError(f"slot '{config.provider}' has no OpenAI-compatible endpoint")
        self.config = config
        self.transport = transport or default_transport
        self.timeout = timeout
        self.endpoint = endpoint or OPENAI_COMPAT_ENDPOINTS[config.provider]

    def chat(self, messages: list, max_tokens: int = 256, model: Optional[str] = None) -> AIResponse:
        if not self.config.is_configured:
            return AIResponse(ok=False, status=AIStatus.NOT_CONFIGURED, code="NO_TOKEN",
                              provider=self.config.provider)
        use_model = model or self.config.model or self.endpoint["model"]
        url = f"{self.endpoint['base']}/chat/completions"
        req = {
            "method": "POST",
            "headers": {
                "Authorization": f"Bearer {self.config.api_token}",
                "Content-Type": "application/json",
            },
            "body": json.dumps({"model": use_model, "max_tokens": max_tokens, "messages": list(messages)}),
            "timeout": self.timeout,
        }
        t0 = now_ms()
        try:
            status, raw, _hdrs = self.transport(url, req)
        except Exception:  # noqa: BLE001 - honest network bucket
            return AIResponse(ok=False, status=AIStatus.NETWORK_ERROR, code="NETWORK_ERROR",
                              provider=self.config.provider, model=use_model, elapsed_ms=now_ms() - t0)
        elapsed = now_ms() - t0
        try:
            body = json.loads(raw.decode("utf-8", "replace")) if raw else {}
        except ValueError:
            body = {}
        if status in (401, 403):
            return AIResponse(ok=False, status=AIStatus.AUTH_FAILED, code=f"HTTP_{status}",
                              provider=self.config.provider, model=use_model, elapsed_ms=elapsed,
                              detail=f"{self.endpoint['label']} rejected the key")
        if status == 429:
            return AIResponse(ok=False, status=AIStatus.RATE_LIMITED, code="HTTP_429",
                              provider=self.config.provider, model=use_model, elapsed_ms=elapsed,
                              detail="rate/quota limit — key may still be valid")
        if status != 200:
            return AIResponse(ok=False, status=AIStatus.NETWORK_ERROR, code=f"HTTP_{status}",
                              provider=self.config.provider, model=use_model, elapsed_ms=elapsed)
        choices = body.get("choices") if isinstance(body, dict) else None
        text = None
        if isinstance(choices, list) and choices and isinstance(choices[0], dict):
            msg = choices[0].get("message")
            if isinstance(msg, dict) and isinstance(msg.get("content"), str):
                text = msg["content"]
        if text is None:
            return AIResponse(ok=False, status=AIStatus.NETWORK_ERROR, code="UNEXPECTED_BODY",
                              provider=self.config.provider, model=use_model, elapsed_ms=elapsed)
        return AIResponse(ok=True, status=AIStatus.VERIFIED, provider=self.config.provider,
                          model=use_model, text=text, elapsed_ms=elapsed)


def load_slot_provider(slot: str, transport: Optional[Transport] = None) -> OpenAICompatProvider:
    """Load a vault slot as an OpenAI-compatible provider (graceful if empty)."""
    cfg = load_vault_slot(slot)
    if cfg.provider != slot:  # load_vault_slot returns provider=slot either way
        cfg = AIProviderConfig(provider=slot)
    return OpenAICompatProvider(cfg, transport=transport)


def token_masked_for(slot: str) -> str:
    cfg = load_vault_slot(slot)
    return mask_secret(cfg.api_token) or "(none)"
