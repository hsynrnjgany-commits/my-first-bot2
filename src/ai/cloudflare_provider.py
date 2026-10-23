"""MARI — Cloudflare Workers AI provider (independent verify parser + self-test).

Rebuild of Task 65 after the Task 69 environment rollback. Honest by design:
- verify_token parses the verify endpoint body independently (no inference-path reuse).
- TOKEN_DISABLED / TOKEN_EXPIRED are distinct honest outcomes.
- Inference needs account_id; if discovery fails, the owner registers it in the
  dashboard vault and the fleet reads the vault first (config.SEARCH_PATHS).
- Exit codes for the self-test CLI: 0 OK, 2 AUTH_FAILED, 3 NETWORK, 4 NOT_CONFIGURED.
READ ONLY | PAPER ONLY | NO LIVE ORDERS
"""

import json
import os
import sys
import time
import urllib.error
import urllib.request
from typing import Callable, Dict, Optional, Tuple

from src.ai.config import AIProviderConfig, load_provider_config, mask_secret
from src.ai.provider import AIResponse, AIStatus, now_ms

CF_BASE = "https://api.cloudflare.com/client/v4"
DEFAULT_MODEL = "@cf/meta/llama-3.1-8b-instruct"

# (status, body_bytes, headers)
Transport = Callable[[str, dict], Tuple[int, bytes, Dict[str, str]]]


def default_transport(url: str, req: dict) -> Tuple[int, bytes, Dict[str, str]]:
    """Real HTTP via urllib — injectable for offline tests."""
    timeout = float(req.get("timeout", 20))
    data = req.get("body")
    r = urllib.request.Request(
        url,
        data=data.encode("utf-8") if isinstance(data, str) else data,
        headers=req.get("headers") or {},
        method=req.get("method", "GET"),
    )
    try:
        with urllib.request.urlopen(r, timeout=timeout) as resp:
            return int(resp.status), resp.read(), dict(resp.headers)
    except urllib.error.HTTPError as e:  # non-2xx is still a usable response
        return int(e.code), e.read(), dict(e.headers or {})


class CloudflareProvider:
    """Workers AI client — token stays private; every claim comes from a real reply."""

    def __init__(
        self,
        config: AIProviderConfig,
        transport: Optional[Transport] = None,
        base_url: str = CF_BASE,
        timeout: float = 20.0,
    ):
        self.config = config
        self.transport = transport or default_transport
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    # ------------------------------------------------------------ helpers

    def _headers(self) -> Dict[str, str]:
        return {
            "Authorization": f"Bearer {self.config.api_token}",
            "Content-Type": "application/json",
        }

    def _call(self, path: str, body: Optional[dict] = None) -> Tuple[int, dict]:
        url = f"{self.base_url}{path}"
        req = {"method": "POST" if body is not None else "GET", "headers": self._headers(), "timeout": self.timeout}
        if body is not None:
            req["body"] = json.dumps(body)
        status, raw, _hdrs = self.transport(url, req)
        try:
            parsed = json.loads(raw.decode("utf-8", "replace")) if raw else {}
        except ValueError:
            parsed = {}
        return status, parsed if isinstance(parsed, dict) else {}

    # ------------------------------------------------------------- verify

    def verify_token(self) -> AIResponse:
        """GET /user/tokens/verify — independent body mapping (Task 65 fix)."""
        if not self.config.is_configured:
            return AIResponse(ok=False, status=AIStatus.NOT_CONFIGURED, code="NO_TOKEN",
                              provider="cloudflare", detail="token missing on all layers")
        t0 = now_ms()
        status, body = self._call("/user/tokens/verify")
        elapsed = now_ms() - t0
        success = body.get("success") is True
        result = body.get("result") if isinstance(body.get("result"), dict) else {}
        token_status = str(result.get("status") or "").lower()

        if status == 200 and success and token_status == "active":
            return AIResponse(ok=True, status=AIStatus.VERIFIED, provider="cloudflare",
                              model=None, elapsed_ms=elapsed, detail="token active per real verify reply")
        if token_status == "disabled":
            return AIResponse(ok=False, status=AIStatus.AUTH_FAILED, code="TOKEN_DISABLED",
                              provider="cloudflare", elapsed_ms=elapsed, detail="Cloudflare reports token disabled")
        if token_status == "expired":
            return AIResponse(ok=False, status=AIStatus.AUTH_FAILED, code="TOKEN_EXPIRED",
                              provider="cloudflare", elapsed_ms=elapsed, detail="Cloudflare reports token expired")
        if status in (401, 403):
            code = None
            errs = body.get("errors")
            if isinstance(errs, list) and errs and isinstance(errs[0], dict):
                code = f"CF_{errs[0].get('code')}" if errs[0].get("code") is not None else None
            return AIResponse(ok=False, status=AIStatus.AUTH_FAILED, code=code or f"HTTP_{status}",
                              provider="cloudflare", elapsed_ms=elapsed, detail="credential rejected by Cloudflare")
        if status == 429:
            return AIResponse(ok=False, status=AIStatus.RATE_LIMITED, code="HTTP_429",
                              provider="cloudflare", elapsed_ms=elapsed)
        if status >= 500 or status == 0:
            return AIResponse(ok=False, status=AIStatus.NETWORK_ERROR, code=f"HTTP_{status}",
                              provider="cloudflare", elapsed_ms=elapsed)
        return AIResponse(ok=False, status=AIStatus.NETWORK_ERROR, code=f"UNEXPECTED_HTTP_{status}",
                          provider="cloudflare", elapsed_ms=elapsed,
                          detail="verify reply did not match any documented shape")

    # ---------------------------------------------------------- discovery

    def discover_account(self) -> AIResponse:
        """GET /accounts — account-scoped tokens legitimately return an empty list."""
        t0 = now_ms()
        status, body = self._call("/accounts")
        elapsed = now_ms() - t0
        if status == 200:
            result = body.get("result")
            if isinstance(result, list) and result and isinstance(result[0], dict) and result[0].get("id"):
                return AIResponse(ok=True, status=AIStatus.VERIFIED, provider="cloudflare",
                                  elapsed_ms=elapsed, text=str(result[0]["id"]),
                                  detail="account discovered")
            return AIResponse(ok=False, status=AIStatus.NETWORK_ERROR, code="ACCOUNT_LIST_EMPTY",
                              provider="cloudflare", elapsed_ms=elapsed,
                              detail="token is account-scoped: register account_id manually in the vault")
        if status in (401, 403):
            return AIResponse(ok=False, status=AIStatus.AUTH_FAILED, code=f"HTTP_{status}",
                              provider="cloudflare", elapsed_ms=elapsed)
        if status == 429:
            return AIResponse(ok=False, status=AIStatus.RATE_LIMITED, code="HTTP_429",
                              provider="cloudflare", elapsed_ms=elapsed)
        return AIResponse(ok=False, status=AIStatus.NETWORK_ERROR, code=f"HTTP_{status}",
                          provider="cloudflare", elapsed_ms=elapsed)

    # ----------------------------------------------------------- inference

    def run_inference(
        self,
        messages: list,
        model: Optional[str] = None,
        max_tokens: int = 256,
        role=None,
    ) -> AIResponse:
        """POST /accounts/{account_id}/ai/run/{model} — analysis-only output."""
        if not self.config.is_configured:
            return AIResponse(ok=False, status=AIStatus.NOT_CONFIGURED, code="NO_TOKEN", provider="cloudflare")
        if not self.config.account_id:
            return AIResponse(ok=False, status=AIStatus.READY, code="NO_ACCOUNT_ID",
                              provider="cloudflare", model=model or self.config.model or DEFAULT_MODEL,
                              detail="account_id missing — register it in the dashboard vault")
        use_model = model or self.config.model or DEFAULT_MODEL
        payload = {"messages": list(messages), "max_tokens": max_tokens}
        t0 = now_ms()
        status, body = self._call(f"/accounts/{self.config.account_id}/ai/run/{use_model}", payload)
        elapsed = now_ms() - t0
        if status == 200:
            result = body.get("result")
            text: Optional[str] = None
            if isinstance(result, dict):
                r = result.get("response")
                if isinstance(r, str):
                    text = r
                elif isinstance(r, dict) and isinstance(r.get("content"), str):
                    text = r["content"]
            if text is None:
                return AIResponse(ok=False, status=AIStatus.NETWORK_ERROR, code="UNEXPECTED_BODY",
                                  provider="cloudflare", model=use_model, elapsed_ms=elapsed)
            return AIResponse(ok=True, status=AIStatus.VERIFIED, provider="cloudflare",
                              model=use_model, text=text, elapsed_ms=elapsed, role=role)
        if status in (401, 403):
            return AIResponse(ok=False, status=AIStatus.AUTH_FAILED, code=f"HTTP_{status}",
                              provider="cloudflare", model=use_model, elapsed_ms=elapsed)
        if status == 429:
            return AIResponse(ok=False, status=AIStatus.RATE_LIMITED, code="HTTP_429",
                              provider="cloudflare", model=use_model, elapsed_ms=elapsed)
        return AIResponse(ok=False, status=AIStatus.NETWORK_ERROR, code=f"HTTP_{status}",
                          provider="cloudflare", model=use_model, elapsed_ms=elapsed)

    # ----------------------------------------------------------- self-heal

    def save_discovered_account(self, config_path: Optional[str] = None) -> Optional[str]:
        """Discover account_id and write it back into the config file (self-heal)."""
        disc = self.discover_account()
        if not (disc.ok and disc.text):
            return None
        path = config_path or self.config.config_path
        if not path or not os.path.isfile(path):
            return None
        try:
            with open(path, "r", encoding="utf-8") as fh:
                data = json.load(fh)
            if not isinstance(data, dict):
                return None
            data["account_id"] = disc.text
            fd = os.open(path, os.O_WRONLY | os.O_TRUNC, 0o600)
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                json.dump(data, fh, indent=2, ensure_ascii=False)
            os.chmod(path, 0o600)
        except (OSError, ValueError):
            return None
        return disc.text


# ------------------------------------------------------------------ self-test

def _print_report(mask: str, reports: list) -> int:
    """Print honest JSON report; return process exit code."""
    codes = {r.status for _step, r in reports}
    if AIStatus.AUTH_FAILED in codes:
        exit_code = 2
    elif AIStatus.NETWORK_ERROR in codes or AIStatus.RATE_LIMITED in codes:
        exit_code = 3
    elif AIStatus.NOT_CONFIGURED in codes:
        exit_code = 4
    else:
        exit_code = 0
    payload = {
        "provider": "cloudflare",
        "token_masked": mask,
        "reports": [
            {
                "step": step,
                "ok": r.ok,
                "status": r.status.value,
                "code": r.code,
                "detail": r.detail,
                "elapsed_ms": r.elapsed_ms,
            }
            for step, r in reports
        ],
        "exit_code": exit_code,
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return exit_code


def run_self_test(config: Optional[AIProviderConfig] = None) -> int:
    """verify -> discover -> (self-heal) -> small inference. Honest at every step."""
    cfg = config or load_provider_config()
    provider = CloudflareProvider(cfg)
    mask = cfg.token_masked or "(none)"
    reports = []

    verify = provider.verify_token()
    reports.append(("verify", verify))
    if verify.status is AIStatus.NOT_CONFIGURED:
        return _print_report(mask, reports)
    if verify.status is not AIStatus.VERIFIED:
        return _print_report(mask, reports)

    # account_id: from config, else discover + self-heal
    if not cfg.account_id:
        disc = provider.discover_account()
        reports.append(("discover_account", disc))
        if disc.ok and disc.text:
            saved = provider.save_discovered_account()
            reports.append(("save_discovered_account", AIResponse(
                ok=saved is not None, status=AIStatus.VERIFIED if saved else AIStatus.NETWORK_ERROR,
                code=None if saved else "SAVE_FAILED", provider="cloudflare",
                detail="account_id persisted" if saved else "could not persist account_id")))
            if saved:
                cfg = AIProviderConfig(
                    provider="cloudflare", api_token=cfg.api_token, account_id=saved,
                    model=cfg.model, config_path=cfg.config_path, found_via=cfg.found_via,
                )
                provider = CloudflareProvider(cfg)
    else:
        reports.append(("discover_account", AIResponse(
            ok=True, status=AIStatus.VERIFIED, provider="cloudflare",
            detail="account_id already registered in config")))

    inference = provider.run_inference(
        [{"role": "user", "content": "Reply with exactly: OK"}],
        max_tokens=8,
    )
    reports.append(("inference", inference))
    return _print_report(mask, reports)


if __name__ == "__main__":  # pragma: no cover - live entry
    sys.exit(run_self_test())
