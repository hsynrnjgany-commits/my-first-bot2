"""MARI — GitHub Actions relay provider (4th brain path: OpenAI via Azure egress).

OpenAI geo-blocks BOTH the server egress AND the Cloudflare shared IPv6 pool
(region hunt Task 75: same egress IP from every CF region, always 403). GitHub
hosted runners egress from Azure (US) IPs that OpenAI accepts. This adapter:

  1. dispatches workflow ``mari-openai-relay.yml`` with a request id + payload
     (the OpenAI key never travels with the request — it lives in the repo
     secret MARI_OPENAI_KEY and is mounted only inside the runner)
  2. polls ``relay-outbox/<request_id>.json`` (committed by the runner)
  3. maps the result onto the same honest AIResponse semantics as the other
     providers: no claim of success without a real vendor 200.

Latency is 20-90s (queue + run + commit) — fine for analysis-only scanning.
READ ONLY | PAPER ONLY | NO LIVE ORDERS
"""
import base64
import json
import time
import uuid
from typing import Callable, Dict, Optional, Tuple

from src.ai.cloudflare_provider import Transport, default_transport
from src.ai.config import AIProviderConfig, load_vault_slot, mask_secret
from src.ai.provider import AIResponse, AIStatus, now_ms

WORKFLOW_FILE = "mari-openai-relay.yml"
OUTBOX_DIR = "relay-outbox"
REPO_FALLBACK = "hsynrnjgany-commits/my-first-bot2"
DEFAULT_MODEL = "gpt-4o-mini"
API = "https://api.github.com"


class GitHubRelayProvider:
    """Dispatch -> runner (Azure egress) -> OpenAI -> outbox -> AIResponse."""

    def __init__(
        self,
        config: AIProviderConfig,
        transport: Optional[Transport] = None,
        poll_interval: float = 4.0,
        poll_timeout: float = 150.0,
    ):
        self.config = config
        self.transport = transport or default_transport
        self.poll_interval = poll_interval
        self.poll_timeout = poll_timeout

    @property
    def repo(self) -> str:
        return REPO_FALLBACK

    def _gh(self, method: str, path: str, body: Optional[dict] = None) -> Tuple[int, bytes]:
        req = {
            "method": method,
            "headers": {
                "Authorization": f"Bearer {self.config.api_token}",
                "Accept": "application/vnd.github+json",
                "User-Agent": "mari-paper-research/1.0",
            },
            "timeout": 30.0,
        }
        if body is not None:
            req["body"] = json.dumps(body).encode("utf-8")
        url = f"{API}{path}"
        try:
            status, raw, _hdrs = self.transport(url, req)
            return status, raw
        except Exception:  # noqa: BLE001 - honest network bucket
            return 0, b""

    def _dispatch(self, request_id: str, payload_str: str, mode: str) -> Tuple[bool, str]:
        status, raw = self._gh(
            "POST",
            f"/repos/{self.repo}/actions/workflows/{WORKFLOW_FILE}/dispatches",
            {"ref": "main", "inputs": {"request_id": request_id, "payload": payload_str, "mode": mode}},
        )
        if status == 204:
            return True, "DISPATCH_OK"
        detail = raw.decode("utf-8", "replace")[:180] if raw else ""
        return False, f"DISPATCH_HTTP_{status or 'NET'}" + (f" {detail}" if detail else "")

    def _read_outbox(self, request_id: str) -> Optional[dict]:
        status, raw = self._gh(
            "GET", f"/repos/{self.repo}/contents/{OUTBOX_DIR}/{request_id}.json?ref=main",
        )
        if status != 200:
            return None
        try:
            meta = json.loads(raw.decode("utf-8", "replace"))
            content = base64.b64decode(meta.get("content", "")).decode("utf-8", "replace")
            data = json.loads(content)
            return data if isinstance(data, dict) else None
        except (ValueError, KeyError, TypeError):
            return None

    def relay_call(self, mode: str, payload: dict) -> Dict[str, object]:
        """One dispatch+poll round trip; honest report dict at the end."""
        rid = uuid.uuid4().hex[:16]
        report: Dict[str, object] = {"request_id": rid, "mode": mode}
        t0 = now_ms()
        ok, code = self._dispatch(rid, json.dumps(payload), mode)
        if not ok:
            report.update({"ok": False, "code": code, "elapsed_ms": now_ms() - t0})
            return report
        deadline = time.monotonic() + self.poll_timeout
        while time.monotonic() < deadline:
            outbox = self._read_outbox(rid)
            if outbox is not None:
                report.update({
                    "ok": bool(outbox.get("ok")),
                    "http": outbox.get("http"),
                    "body": outbox.get("body"),
                    "elapsed_ms": now_ms() - t0,
                })
                return report
            time.sleep(self.poll_interval)
        report.update({"ok": False, "code": "OUTBOX_TIMEOUT", "elapsed_ms": now_ms() - t0})
        return report

    def chat(self, messages: list, max_tokens: int = 256, model: Optional[str] = None) -> AIResponse:
        if not self.config.is_configured:
            return AIResponse(ok=False, status=AIStatus.NOT_CONFIGURED, code="NO_TOKEN",
                              provider="openai-relay")
        payload = {"model": model or DEFAULT_MODEL, "max_tokens": max_tokens,
                   "messages": list(messages)}
        rep = self.relay_call("chat", payload)
        base = dict(provider="openai-relay", model=payload["model"],
                    elapsed_ms=rep.get("elapsed_ms"))
        if rep.get("code") == "OUTBOX_TIMEOUT":
            return AIResponse(ok=False, status=AIStatus.NETWORK_ERROR, code="OUTBOX_TIMEOUT",
                              detail="runner never committed the outbox in time", **base)
        if not rep.get("ok") and rep.get("http") in (None, 0):
            return AIResponse(ok=False, status=AIStatus.NETWORK_ERROR,
                              code=str(rep.get("code") or "DISPATCH_FAILED"),
                              detail=str(rep.get("code")), **base)
        http = rep.get("http")
        raw = rep.get("body") if isinstance(rep.get("body"), str) else ""
        snippet = raw[:220] if raw else ""
        if http in (401, 403):
            return AIResponse(ok=False, status=AIStatus.AUTH_FAILED, code=f"HTTP_{http}",
                              detail=snippet or "runner key rejected", **base)
        if http == 429:
            return AIResponse(ok=False, status=AIStatus.RATE_LIMITED, code="HTTP_429",
                              detail=snippet or "rate/quota limit", **base)
        if http != 200:
            return AIResponse(ok=False, status=AIStatus.NETWORK_ERROR, code=f"HTTP_{http}",
                              detail=snippet or None, **base)
        try:
            body = json.loads(raw) if raw else {}
            text = body["choices"][0]["message"]["content"]
        except (ValueError, KeyError, IndexError, TypeError):
            return AIResponse(ok=False, status=AIStatus.NETWORK_ERROR, code="UNEXPECTED_BODY",
                              **base)
        return AIResponse(ok=True, status=AIStatus.VERIFIED, text=text, **base)


def token_masked_for() -> str:
    cfg = load_vault_slot("github")
    return mask_secret(cfg.api_token) or "(none)"


def _row(step: str, resp: AIResponse) -> Dict[str, object]:
    row: Dict[str, object] = {
        "step": step, "ok": resp.ok, "status": resp.status.value, "code": resp.code,
        "provider": resp.provider, "model": resp.model, "detail": resp.detail,
        "elapsed_ms": resp.elapsed_ms,
    }
    if resp.text:
        row["text"] = resp.text[:80]
    return row


def run_self_test() -> int:
    """models-list then one tiny chat through the relay. Honest exit code."""
    cfg = load_vault_slot("github")
    if not cfg.is_configured:
        print(json.dumps({"provider": "openai-relay", "pat_masked": "(none)", "reports": [
            _row("load_slot", AIResponse(ok=False, status=AIStatus.NOT_CONFIGURED,
                                         code="NO_TOKEN", provider="openai-relay")),
        ]}, ensure_ascii=False))
        return 1
    relay = GitHubRelayProvider(cfg)
    reports = [_row("load_slot", AIResponse(ok=True, status=AIStatus.VERIFIED,
                                            provider="openai-relay",
                                            detail=f"pat {cfg.token_masked}"))]
    models_rep = relay.relay_call("models", {})
    model_ids: list = []
    if models_rep.get("ok") and isinstance(models_rep.get("body"), str):
        try:
            data = json.loads(str(models_rep["body"]))
            model_ids = [m.get("id") for m in data.get("data", []) if isinstance(m, dict)]
        except ValueError:
            pass
    reports.append({"step": "models", "ok": bool(models_rep.get("ok")),
                    "http": models_rep.get("http"), "count": len(model_ids),
                    "has_gpt_4o_mini": "gpt-4o-mini" in model_ids,
                    "elapsed_ms": models_rep.get("elapsed_ms")})
    chat = relay.chat([{"role": "user", "content": "Reply with exactly: OK"}], max_tokens=8)
    reports.append(_row("chat", chat))
    print(json.dumps({"provider": "openai-relay", "pat_masked": cfg.token_masked,
                      "reports": reports}, ensure_ascii=False))
    return 0 if chat.ok else 1


if __name__ == "__main__":  # pragma: no cover - live entry
    import sys

    sys.exit(run_self_test())
