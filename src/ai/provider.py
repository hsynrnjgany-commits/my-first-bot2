"""MARI — vendor-neutral AI provider interface (5 agency roles, 6 honest states).

Principles (AI_CLUSTER_PLAN.md):
- No claim of successful connection until tested against the real API.
- AI output is analysis-only, NEVER a trading signal.
- Errors are mapped to honest statuses; nothing passes silently.
READ ONLY | PAPER ONLY | NO LIVE ORDERS
"""

import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


class AIRole(str, Enum):
    """The five agency roles from AI_CLUSTER_PLAN.md section 3."""

    MARKET_ANALYST = "market_analyst"
    RESEARCH_AGENT = "research_agent"
    VALIDATION_AGENT = "validation_agent"
    RISK_AGENT = "risk_agent"
    COORDINATOR_AGENT = "coordinator_agent"


class AIStatus(str, Enum):
    """Six honest connection/inference states — no lies, no silent passes."""

    NOT_CONFIGURED = "not_configured"      # no token on any layer
    READY = "ready"                        # token present, not yet verified
    VERIFIED = "verified"                  # real API confirmed the credential
    AUTH_FAILED = "auth_failed"            # real API rejected the credential
    NETWORK_ERROR = "network_error"        # timeout/unreachable/5xx
    RATE_LIMITED = "rate_limited"          # 429 quota/throttle


@dataclass(frozen=True)
class AIResponse:
    """Result envelope — never contains the raw token; repr is mask-safe."""

    ok: bool
    status: AIStatus
    code: Optional[str] = None
    detail: Optional[str] = None
    text: Optional[str] = None
    provider: str = ""
    model: Optional[str] = None
    role: Optional[AIRole] = None
    elapsed_ms: int = 0
    meta: dict = field(default_factory=dict)

    def __repr__(self) -> str:  # pragma: no cover - cosmetic
        return (
            f"AIResponse(ok={self.ok}, status={self.status.value}, "
            f"code={self.code!r}, provider={self.provider!r}, "
            f"model={self.model!r}, elapsed_ms={self.elapsed_ms})"
        )


ROLE_SYSTEM_PROMPTS: dict = {
    AIRole.MARKET_ANALYST: (
        "You are the MARKET_ANALYST of a read-only paper-trading research system. "
        "Analyze price action, liquidity, AMD phases, sessions and market regimes "
        "from the provided datasets. Output analysis only — never trading orders."
    ),
    AIRole.RESEARCH_AGENT: (
        "You are the RESEARCH_AGENT. Discover hypotheses and investigate historical "
        "market behavior from the evidence provided. Output hypotheses with explicit "
        "uncertainty — never trading orders."
    ),
    AIRole.VALIDATION_AGENT: (
        "You are the VALIDATION_AGENT. Check data quality, historical results and "
        "out-of-sample performance. Be skeptical; flag anything unverifiable."
    ),
    AIRole.RISK_AGENT: (
        "You are the RISK_AGENT. Evaluate drawdown, transaction costs and liquidity "
        "constraints. Always state worst-case scenarios first."
    ),
    AIRole.COORDINATOR_AGENT: (
        "You are the COORDINATOR_AGENT. Organize analytical tasks and compare agent "
        "outputs; surface disagreements instead of averaging them away."
    ),
}


def role_system_prompt(role: AIRole) -> str:
    return ROLE_SYSTEM_PROMPTS[role]


def now_ms() -> int:
    return int(time.time() * 1000)
