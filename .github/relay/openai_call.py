"""MARI — OpenAI relay caller (runs INSIDE the GitHub Actions runner).

Runner egress = Azure (US) IPs accepted by OpenAI — unlike the Cloudflare
shared pool that OpenAI geo-blocks. Reads the key from the repo secret via
env, never prints it, and writes an honest outbox file either way (HTTP
error bodies are diagnostics, not failures to hide).
READ ONLY | PAPER ONLY | NO LIVE ORDERS
"""
import json
import os
import time
import urllib.error
import urllib.request

OUTBOX_DIR = "relay-outbox"


def _write_outbox(request_id: str, out: dict) -> None:
    os.makedirs(OUTBOX_DIR, exist_ok=True)
    out["ts"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    path = os.path.join(OUTBOX_DIR, f"{request_id}.json")
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(out, fh, ensure_ascii=False)
    print(f"outbox written for {request_id} http={out.get('http')} ok={out.get('ok')}")


def main() -> None:
    key = os.environ.get("OPENAI_KEY", "")
    gh_token = os.environ.get("GH_MODELS_TOKEN", "")
    request_id = os.environ.get("REQUEST_ID", "unknown")
    mode = os.environ.get("MODE", "chat")
    payload_raw = os.environ.get("PAYLOAD", "{}")
    out: dict = {"ok": False, "mode": mode, "http": None, "body": None, "elapsed_ms": None}
    if not request_id or request_id == "unknown":
        out["body"] = "missing REQUEST_ID env"
        _write_outbox(request_id, out)
        return
    if mode == "gh-models":
        if not gh_token:
            out["body"] = "missing GH_MODELS_TOKEN env (workflow must expose github.token)"
            _write_outbox(request_id, out)
            return
    elif not key:
        out["body"] = "missing OPENAI_KEY env"
        _write_outbox(request_id, out)
        return
    t0 = time.time()
    try:
        if mode == "models":
            req = urllib.request.Request(
                "https://api.openai.com/v1/models", method="GET",
                headers={"Authorization": f"Bearer {key}", "Accept": "application/json"},
            )
        elif mode == "gh-models":
            # GitHub Models — same PAT-free path: built-in GITHUB_TOKEN with
            # models: read; no repo secret involved. Serves OpenAI-class
            # models on the free tier from the runner's Azure egress.
            body = json.loads(payload_raw) if payload_raw else {}
            req = urllib.request.Request(
                "https://models.github.ai/inference/chat/completions", method="POST",
                data=json.dumps(body).encode("utf-8"),
                headers={
                    "Authorization": f"Bearer {gh_token}",
                    "Content-Type": "application/json",
                    "Accept": "application/json",
                    "User-Agent": "mari-paper-research/1.0",
                },
            )
        else:
            body = json.loads(payload_raw) if payload_raw else {}
            req = urllib.request.Request(
                "https://api.openai.com/v1/chat/completions", method="POST",
                data=json.dumps(body).encode("utf-8"),
                headers={
                    "Authorization": f"Bearer {key}",
                    "Content-Type": "application/json",
                    "Accept": "application/json",
                },
            )
        with urllib.request.urlopen(req, timeout=60) as resp:
            out["http"] = resp.status
            out["body"] = resp.read().decode("utf-8", "replace")[:200000]
            out["ok"] = resp.status == 200
    except urllib.error.HTTPError as exc:
        out["http"] = exc.code
        try:
            out["body"] = exc.read().decode("utf-8", "replace")[:10000]
        except Exception:  # noqa: BLE001 - diagnostics must never crash
            out["body"] = f"HTTP_{exc.code} (unreadable body)"
    except Exception as exc:  # noqa: BLE001 - honest runner-side bucket
        out["body"] = f"runner_error={type(exc).__name__}: {str(exc)[:300]}"
    out["elapsed_ms"] = int((time.time() - t0) * 1000)
    # defensive: never persist the key even if a vendor echo ever happens
    if isinstance(out.get("body"), str):
        if key:
            out["body"] = out["body"].replace(key, "sk-***")
        if gh_token:
            out["body"] = out["body"].replace(gh_token, "gh_token_***")
    _write_outbox(request_id, out)


if __name__ == "__main__":
    main()
