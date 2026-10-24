"""MARI — offline tests for the AI cluster rebuild (Task 69).

HTTP is mocked via the transport seam; no real network, no secrets.
READ ONLY | PAPER ONLY | NO LIVE ORDERS
"""

import base64
import io
import json
import sys
import urllib.error
from contextlib import redirect_stdout

import pytest

from src.ai.config import (
    AIProviderConfig,
    load_provider_config,
    load_vault_slot,
    mask_secret,
)
from src.ai.provider import AIResponse, AIStatus
from src.ai.cloudflare_provider import CloudflareProvider, run_self_test
from src.ai.github_relay_provider import GitHubRelayProvider
from src.ai.openai_compat_provider import OpenAICompatProvider, load_slot_provider

# ------------------------------------------------------------------ helpers


def make_transport(routes):
    """routes: list of (path_suffix_matcher, (status, body_dict)). Sequential pop."""

    def transport(url, req):
        for i, (match, resp) in enumerate(routes):
            if match in url:
                return resp[0], json.dumps(resp[1]).encode("utf-8"), {}
        raise AssertionError(f"unexpected URL: {url}")

    return transport


def cfg(token="cfut_testtoken1234567890", account_id=None, provider="cloudflare", model=None):
    return AIProviderConfig(provider=provider, api_token=token, account_id=account_id, model=model)


VERIFY_ACTIVE = (200, {"success": True, "result": {"status": "active"}})
ACCOUNTS_FOUND = (200, {"success": True, "result": [{"id": "a" * 32, "name": "acme"}]})
ACCOUNTS_EMPTY = (200, {"success": True, "result": []})
RUN_OK = (200, {"success": True, "result": {"response": "OK"}})
RUN_OK_DICT = (200, {"success": True, "result": {"response": {"role": "assistant", "content": "OK"}}})


# ------------------------------------------------------------------- config


def test_mask_secret_shape():
    assert mask_secret("cfut_abcdefghijklmnop") == "cfut_...mnop"
    assert mask_secret("short") == "***"
    assert mask_secret("") == ""


def test_mask_never_leaks_full_token():
    tok = "cfut_supersecretvalue123456"
    m = mask_secret(tok)
    assert tok not in m and m.startswith("cfut_") and m.endswith("456")


def test_load_provider_config_missing_is_not_error():
    c = load_provider_config(search_paths=("/nonexistent/x.json",))
    assert c.is_configured is False
    assert c.api_token is None


def test_load_provider_config_reads_token_and_account(tmp_path):
    p = tmp_path / "cf.json"
    p.write_text(json.dumps({"provider": "cloudflare", "api_token": "tok123456789", "account_id": "a" * 32}))
    c = load_provider_config(search_paths=(str(p),))
    assert c.is_configured and c.account_id == "a" * 32


def test_load_provider_config_skips_other_provider(tmp_path):
    p = tmp_path / "x.json"
    p.write_text(json.dumps({"provider": "other", "api_token": "tok123456789"}))
    c = load_provider_config(search_paths=(str(p),))
    assert not c.is_configured


def test_load_provider_config_corrupt_json_skipped(tmp_path):
    p = tmp_path / "bad.json"
    p.write_text("{not json")
    c = load_provider_config(search_paths=(str(p),))
    assert not c.is_configured


def test_vault_slot_loader_reads_accountId(tmp_path, monkeypatch):
    import src.ai.config as cfgmod

    vault = tmp_path / "vault"
    vault.mkdir()
    (vault / "cloudflare.json").write_text(
        json.dumps({"token": "cfut_vaulttoken12345", "accountId": "b" * 32})
    )
    monkeypatch.setattr(cfgmod, "VAULT_DIR", str(vault))
    monkeypatch.setattr(cfgmod, "VAULT_L4_DIR", str(tmp_path / "missing"))
    c = load_vault_slot("cloudflare")
    assert c.api_token == "cfut_vaulttoken12345"
    assert c.account_id == "b" * 32
    assert c.found_via == str(vault)


def test_vault_slot_loader_missing_slot_is_not_configured(tmp_path, monkeypatch):
    import src.ai.config as cfgmod

    monkeypatch.setattr(cfgmod, "VAULT_DIR", str(tmp_path / "nope"))
    monkeypatch.setattr(cfgmod, "VAULT_L4_DIR", str(tmp_path / "nope2"))
    c = load_vault_slot("openai")
    assert not c.is_configured


# ------------------------------------------------------------------- verify


def test_verify_active():
    p = CloudflareProvider(cfg(), transport=make_transport([("/user/tokens/verify", VERIFY_ACTIVE)]))
    r = p.verify_token()
    assert r.ok and r.status is AIStatus.VERIFIED


def test_verify_disabled_is_auth_failed_with_code():
    p = CloudflareProvider(cfg(), transport=make_transport(
        [("/user/tokens/verify", (200, {"success": True, "result": {"status": "disabled"}}))]))
    r = p.verify_token()
    assert not r.ok and r.status is AIStatus.AUTH_FAILED and r.code == "TOKEN_DISABLED"


def test_verify_expired_is_auth_failed_with_code():
    p = CloudflareProvider(cfg(), transport=make_transport(
        [("/user/tokens/verify", (200, {"success": True, "result": {"status": "expired"}}))]))
    r = p.verify_token()
    assert r.code == "TOKEN_EXPIRED" and r.status is AIStatus.AUTH_FAILED


def test_verify_401_maps_to_auth_failed():
    p = CloudflareProvider(cfg(), transport=make_transport(
        [("/user/tokens/verify", (401, {"success": False, "errors": [{"code": 1000, "message": "x"}]}))]))
    r = p.verify_token()
    assert r.status is AIStatus.AUTH_FAILED and r.code == "CF_1000"


def test_verify_429_maps_to_rate_limited():
    p = CloudflareProvider(cfg(), transport=make_transport([("/user/tokens/verify", (429, {}))]))
    assert p.verify_token().status is AIStatus.RATE_LIMITED


def test_verify_500_maps_to_network_error():
    p = CloudflareProvider(cfg(), transport=make_transport([("/user/tokens/verify", (500, {}))]))
    assert p.verify_token().status is AIStatus.NETWORK_ERROR


def test_verify_garbage_body_is_honest_unexpected():
    def t(url, req):
        return 200, b"\x00garbage", {}
    r = CloudflareProvider(cfg(), transport=t).verify_token()
    assert not r.ok and r.code == "UNEXPECTED_HTTP_200"


def test_verify_without_token_is_not_configured():
    r = CloudflareProvider(cfg(token=None)).verify_token()
    assert r.status is AIStatus.NOT_CONFIGURED and r.code == "NO_TOKEN"


# ---------------------------------------------------------------- discovery


def test_discover_account_found():
    p = CloudflareProvider(cfg(), transport=make_transport([("/accounts", ACCOUNTS_FOUND)]))
    r = p.discover_account()
    assert r.ok and r.text == "a" * 32


def test_discover_account_empty_list_is_honest():
    p = CloudflareProvider(cfg(), transport=make_transport([("/accounts", ACCOUNTS_EMPTY)]))
    r = p.discover_account()
    assert not r.ok and r.code == "ACCOUNT_LIST_EMPTY"
    assert "account-scoped" in (r.detail or "")


# ---------------------------------------------------------------- inference


def test_inference_ok_string_response():
    p = CloudflareProvider(cfg(account_id="a" * 32),
                           transport=make_transport([("/ai/run/", RUN_OK)]))
    r = p.run_inference([{"role": "user", "content": "hi"}])
    assert r.ok and r.text == "OK" and r.model


def test_inference_ok_dict_content_response():
    p = CloudflareProvider(cfg(account_id="a" * 32),
                           transport=make_transport([("/ai/run/", RUN_OK_DICT)]))
    assert p.run_inference([{"role": "user", "content": "hi"}]).text == "OK"


def test_inference_without_account_id_is_ready_with_code():
    p = CloudflareProvider(cfg(), transport=make_transport([("/ai/run/", RUN_OK)]))
    r = p.run_inference([{"role": "user", "content": "hi"}])
    assert not r.ok and r.code == "NO_ACCOUNT_ID" and r.status is AIStatus.READY


def test_inference_401_is_auth_failed():
    p = CloudflareProvider(cfg(account_id="a" * 32),
                           transport=make_transport([("/ai/run/", (401, {"errors": []}))]))
    assert p.run_inference([{"role": "user", "content": "hi"}]).status is AIStatus.AUTH_FAILED


# ---------------------------------------------------------------- self-heal


def test_save_discovered_account_persists_and_keeps_600(tmp_path):
    p = tmp_path / "cfg.json"
    p.write_text(json.dumps({"provider": "cloudflare", "api_token": "tok123456789"}))
    prov = CloudflareProvider(cfg(), transport=make_transport([("/accounts", ACCOUNTS_FOUND)]))
    saved = prov.save_discovered_account(config_path=str(p))
    assert saved == "a" * 32
    data = json.loads(p.read_text())
    assert data["account_id"] == "a" * 32
    assert (p.stat().st_mode & 0o777) == 0o600


def test_save_discovered_account_none_when_discovery_fails(tmp_path):
    p = tmp_path / "cfg.json"
    p.write_text(json.dumps({"provider": "cloudflare", "api_token": "tok123456789"}))
    prov = CloudflareProvider(cfg(), transport=make_transport([("/accounts", ACCOUNTS_EMPTY)]))
    assert prov.save_discovered_account(config_path=str(p)) is None


# --------------------------------------------------------------- self-test


def _run_selftest_output(c):
    buf = io.StringIO()
    with redirect_stdout(buf):
        code = run_self_test(c)
    return code, buf.getvalue()


def test_selftest_full_happy_path_exit_zero():
    c = cfg(account_id="a" * 32)
    _orig = CloudflareProvider.__init__

    def patched(self, config, transport=None, base_url="x", timeout=1.0):
        _orig(self, config, transport=make_transport([
            ("/user/tokens/verify", VERIFY_ACTIVE), ("/ai/run/", RUN_OK)]))

    import src.ai.cloudflare_provider as mod
    mod.CloudflareProvider.__init__ = patched
    try:
        code, out = _run_selftest_output(c)
    finally:
        mod.CloudflareProvider.__init__ = _orig
    assert code == 0 and '"exit_code": 0' in out and '"verified"' in out


def test_selftest_auth_failed_exit_two():
    c = cfg()
    _orig = CloudflareProvider.__init__

    def patched(self, config, transport=None, base_url="x", timeout=1.0):
        _orig(self, config, transport=make_transport([("/user/tokens/verify", (401, {"success": False, "errors": []}))]))

    import src.ai.cloudflare_provider as mod
    mod.CloudflareProvider.__init__ = patched
    try:
        code, out = _run_selftest_output(c)
    finally:
        mod.CloudflareProvider.__init__ = _orig
    assert code == 2 and '"auth_failed"' in out and '"exit_code": 2' in out


def test_selftest_not_configured_exit_four():
    code, out = _run_selftest_output(AIProviderConfig(provider="cloudflare"))
    assert code == 4 and "not_configured" in out


def test_selftest_report_never_contains_raw_token():
    tok = "cfut_live_secret_123456789"
    c = cfg(token=tok, account_id="a" * 32)
    _orig = CloudflareProvider.__init__

    def patched(self, config, transport=None, base_url="x", timeout=1.0):
        _orig(self, config, transport=make_transport([
            ("/user/tokens/verify", VERIFY_ACTIVE), ("/ai/run/", RUN_OK)]))

    import src.ai.cloudflare_provider as mod
    mod.CloudflareProvider.__init__ = patched
    try:
        _code, out = _run_selftest_output(c)
    finally:
        mod.CloudflareProvider.__init__ = _orig
    assert tok not in out


# ------------------------------------------------------ openai-compatible


def test_openai_compat_happy():
    p = OpenAICompatProvider(cfg(token="sk_test123456789", provider="openai"),
                             transport=make_transport([("/chat/completions",
                                 (200, {"choices": [{"message": {"content": "OK"}}]}))]))
    r = p.chat([{"role": "user", "content": "hi"}])
    assert r.ok and r.text == "OK" and r.provider == "openai"


def test_openai_compat_401_auth_failed():
    p = OpenAICompatProvider(cfg(token="sk_test123456789", provider="deepseek"),
                             transport=make_transport([("/chat/completions", (401, {}))]))
    assert p.chat([{"role": "user", "content": "hi"}]).status is AIStatus.AUTH_FAILED


def test_openai_compat_429_rate_limited():
    p = OpenAICompatProvider(cfg(token="sk_test123456789", provider="gemini"),
                             transport=make_transport([("/chat/completions", (429, {}))]))
    assert p.chat([{"role": "user", "content": "hi"}]).status is AIStatus.RATE_LIMITED


def test_openai_compat_unexpected_body():
    p = OpenAICompatProvider(cfg(token="sk_test123456789", provider="openai"),
                             transport=make_transport([("/chat/completions", (200, {"nope": 1}))]))
    assert p.chat([{"role": "user", "content": "hi"}]).code == "UNEXPECTED_BODY"


def test_openai_compat_not_configured():
    p = OpenAICompatProvider(AIProviderConfig(provider="openai"))
    assert p.chat([{"role": "user", "content": "hi"}]).status is AIStatus.NOT_CONFIGURED


def test_openai_compat_rejects_unknown_slot():
    with pytest.raises(ValueError):
        OpenAICompatProvider(AIProviderConfig(provider="cloudflare"))


def test_load_slot_provider_missing_vault(tmp_path, monkeypatch):
    import src.ai.config as cfgmod

    monkeypatch.setattr(cfgmod, "VAULT_DIR", str(tmp_path / "none"))
    monkeypatch.setattr(cfgmod, "VAULT_L4_DIR", str(tmp_path / "none2"))
    p = load_slot_provider("deepseek", transport=make_transport([]))
    assert p.chat([{"role": "user", "content": "hi"}]).status is AIStatus.NOT_CONFIGURED


def test_openai_compat_base_override_routes_to_relay():
    seen = {}

    def transport(url, req):
        seen["url"] = url
        seen["headers"] = req["headers"]
        return 200, json.dumps({"choices": [{"message": {"content": "OK"}}]}).encode("utf-8"), {}

    c = AIProviderConfig(
        provider="gemini", api_token="AQ_test123456789", model="gemini-3.8-flash",
        base_override="https://mari-gemini-relay.example.workers.dev/v1beta/openai",
        extra_headers={"x-mari-relay-key": "relay_secret"},
    )
    r = OpenAICompatProvider(c, transport=transport).chat([{"role": "user", "content": "hi"}])
    assert r.ok and r.text == "OK"
    assert seen["url"].startswith(
        "https://mari-gemini-relay.example.workers.dev/v1beta/openai/chat/completions")
    assert seen["headers"]["x-mari-relay-key"] == "relay_secret"
    assert seen["headers"]["Authorization"] == "Bearer AQ_test123456789"


def test_vault_slot_loader_reads_base_and_extra_headers(tmp_path, monkeypatch):
    import src.ai.config as cfgmod

    vault = tmp_path / "vault"
    vault.mkdir()
    (vault / "gemini.json").write_text(json.dumps({
        "token": "AQ_test123456789", "model": "gemini-3.8-flash",
        "base": "https://relay.example.workers.dev/v1beta/openai",
        "extra_headers": {"x-mari-relay-key": "secret"},
    }))
    monkeypatch.setattr(cfgmod, "VAULT_DIR", str(vault))
    monkeypatch.setattr(cfgmod, "VAULT_L4_DIR", str(tmp_path / "missing"))
    c = load_vault_slot("gemini")
    assert c.base_override == "https://relay.example.workers.dev/v1beta/openai"
    assert c.extra_headers == {"x-mari-relay-key": "secret"}


def test_openai_selftest_happy_exit_zero(tmp_path, monkeypatch):
    import src.ai.config as cfgmod
    import src.ai.openai_compat_provider as ocmod

    vault = tmp_path / "vault"
    vault.mkdir()
    (vault / "gemini.json").write_text(json.dumps({"token": "AQ_test123456789"}))
    monkeypatch.setattr(cfgmod, "VAULT_DIR", str(vault))
    monkeypatch.setattr(cfgmod, "VAULT_L4_DIR", str(tmp_path / "missing"))
    monkeypatch.setattr(
        ocmod.OpenAICompatProvider, "chat",
        lambda self, msgs, **kw: AIResponse(ok=True, status=AIStatus.VERIFIED,
                                            provider="gemini", text="OK"))
    buf = io.StringIO()
    with redirect_stdout(buf):
        code = ocmod.run_self_test("gemini")
    assert code == 0
    out = buf.getvalue()
    assert '"verified"' in out and "AQ_test123456789" not in out


def test_openai_selftest_missing_slot_exit_one(tmp_path, monkeypatch):
    import src.ai.config as cfgmod
    import src.ai.openai_compat_provider as ocmod

    monkeypatch.setattr(cfgmod, "VAULT_DIR", str(tmp_path / "none"))
    monkeypatch.setattr(cfgmod, "VAULT_L4_DIR", str(tmp_path / "none2"))
    buf = io.StringIO()
    with redirect_stdout(buf):
        code = ocmod.run_self_test("gemini")
    assert code == 1 and "not_configured" in buf.getvalue()


# --------------------------------------------------------------- envelopes


def test_airesponse_repr_has_no_text_or_token():
    r = AIResponse(ok=True, status=AIStatus.VERIFIED, provider="cloudflare", text="secret-ish")
    assert "secret-ish" not in repr(r)


def test_roles_are_five():
    from src.ai.provider import AIRole

    assert len(list(AIRole)) == 5


def test_statuses_are_six():
    assert len(list(AIStatus)) == 6


# ------------------------------------------------------ github actions relay


def _seq_transport(routes):
    """Sequential transport: advance per matching call, stick to last entry."""
    state = {"i": 0}

    def transport(url, req):
        idx = state["i"]
        for j in range(idx, len(routes)):
            match, resp = routes[j]
            if match in url:
                state["i"] = j + 1
                return resp[0], json.dumps(resp[1]).encode("utf-8"), {}
        # exhausted -> repeat last matching entry forever
        for match, resp in reversed(routes):
            if match in url:
                return resp[0], json.dumps(resp[1]).encode("utf-8"), {}
        raise AssertionError(f"unexpected URL: {url}")

    return transport


def _outbox_entry(http, ok, vendor_body):
    """Contents-API response shape wrapping an outbox file (base64)."""
    outbox = {"ok": ok, "mode": "chat", "http": http, "body": vendor_body,
              "elapsed_ms": 42, "ts": "2026-10-23T00:00:00Z"}
    b64 = base64.b64encode(json.dumps(outbox).encode("utf-8")).decode("ascii")
    return (200, {"content": b64, "encoding": "base64"})


def test_github_relay_dispatch_shape():
    seen = {}

    def transport(url, req):
        seen["url"], seen["req"] = url, req
        return 204, b"", {}

    p = GitHubRelayProvider(cfg(token="ghp_test1234567890", provider="github"), transport=transport)
    ok, code = p._dispatch("rid123", '{"model":"gpt-4o-mini"}', "chat")
    assert ok and code == "DISPATCH_OK"
    assert "/actions/workflows/mari-openai-relay.yml/dispatches" in seen["url"]
    assert seen["req"]["method"] == "POST"
    body = json.loads(seen["req"]["body"].decode("utf-8"))
    assert body["ref"] == "main"
    assert body["inputs"]["request_id"] == "rid123"
    assert body["inputs"]["mode"] == "chat"
    assert json.loads(body["inputs"]["payload"])["model"] == "gpt-4o-mini"


def test_github_relay_happy_chat():
    vendor = json.dumps({"choices": [{"message": {"content": "OK"}}]})
    p = GitHubRelayProvider(
        cfg(token="ghp_test1234567890", provider="github"),
        transport=_seq_transport([
            ("/dispatches", (204, {})),
            ("/contents/relay-outbox/", _outbox_entry(200, True, vendor)),
        ]),
        poll_interval=0.01,
    )
    r = p.chat([{"role": "user", "content": "hi"}])
    assert r.ok and r.text == "OK" and r.provider == "openai-relay"
    assert r.status is AIStatus.VERIFIED and r.elapsed_ms is not None


def test_github_relay_polls_until_outbox_lands():
    vendor = json.dumps({"choices": [{"message": {"content": "later"}}]})
    p = GitHubRelayProvider(
        cfg(token="ghp_test1234567890", provider="github"),
        transport=_seq_transport([
            ("/dispatches", (204, {})),
            ("/contents/relay-outbox/", (404, {"message": "No commit found"})),
            ("/contents/relay-outbox/", _outbox_entry(200, True, vendor)),
        ]),
        poll_interval=0.01,
    )
    r = p.chat([{"role": "user", "content": "hi"}])
    assert r.ok and r.text == "later"


def test_github_relay_outbox_timeout_is_honest():
    p = GitHubRelayProvider(
        cfg(token="ghp_test1234567890", provider="github"),
        transport=_seq_transport([
            ("/dispatches", (204, {})),
            ("/contents/relay-outbox/", (404, {"message": "No commit found"})),
        ]),
        poll_interval=0.01, poll_timeout=0.05,
    )
    r = p.chat([{"role": "user", "content": "hi"}])
    assert not r.ok and r.code == "OUTBOX_TIMEOUT"


def test_github_relay_dispatch_403_is_network_error():
    p = GitHubRelayProvider(
        cfg(token="ghp_test1234567890", provider="github"),
        transport=make_transport([("/dispatches", (403, {"message": "forbidden"}))]),
    )
    r = p.chat([{"role": "user", "content": "hi"}])
    assert r.status is AIStatus.NETWORK_ERROR and "DISPATCH_HTTP_403" in (r.code or "")


def test_github_relay_auth_failed_mapping():
    p = GitHubRelayProvider(
        cfg(token="ghp_test1234567890", provider="github"),
        transport=_seq_transport([
            ("/dispatches", (204, {})),
            ("/contents/relay-outbox/", _outbox_entry(401, False, '{"error":"bad key"}')),
        ]),
        poll_interval=0.01,
    )
    assert p.chat([{"role": "user", "content": "hi"}]).status is AIStatus.AUTH_FAILED


def test_github_relay_429_mapping():
    p = GitHubRelayProvider(
        cfg(token="ghp_test1234567890", provider="github"),
        transport=_seq_transport([
            ("/dispatches", (204, {})),
            ("/contents/relay-outbox/", _outbox_entry(429, False, '{"error":"rate"}')),
        ]),
        poll_interval=0.01,
    )
    assert p.chat([{"role": "user", "content": "hi"}]).status is AIStatus.RATE_LIMITED


def test_github_relay_not_configured():
    p = GitHubRelayProvider(AIProviderConfig(provider="github"))
    assert p.chat([{"role": "user", "content": "hi"}]).status is AIStatus.NOT_CONFIGURED


def test_github_relay_selftest_masks_pat(monkeypatch):
    import src.ai.github_relay_provider as gmod

    monkeypatch.setattr(gmod, "load_vault_slot",
                        lambda slot: cfg(token="ghp_secret_pat_9876543210", provider="github"))
    monkeypatch.setattr(gmod.GitHubRelayProvider, "relay_call", lambda self, mode, payload: {
        "ok": True, "http": 200, "request_id": "x", "mode": mode, "elapsed_ms": 5,
        "body": json.dumps({"data": [{"id": "gpt-4o-mini"}]})})
    monkeypatch.setattr(gmod.GitHubRelayProvider, "chat", lambda self, messages, max_tokens=256, model=None: AIResponse(
        ok=True, status=AIStatus.VERIFIED, provider="openai-relay", model="gpt-4o-mini",
        text="OK", elapsed_ms=5))
    buf = io.StringIO()
    with redirect_stdout(buf):
        code = gmod.run_self_test()
    out = buf.getvalue()
    assert code == 0
    assert "ghp_secret_pat_9876543210" not in out
    assert "ghp_..." in out or "..." in out
    assert "gpt-4o-mini" in out
