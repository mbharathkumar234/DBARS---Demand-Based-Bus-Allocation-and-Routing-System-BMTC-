"""Security Guardrails and Prompt Injection Defense for DBARS AI Layer.

Protects against:
- Prompt injection and jailbreaks ("ignore previous instructions", "DAN mode", "system prompt leakage")
- Unauthorized modification attempts (e.g., attempting to trigger database writes or updates via AI chat)
- Sensitive credential probing
- Hallucination enforcement
"""

from __future__ import annotations

import logging
import re
from typing import Optional, Tuple
from pydantic import BaseModel, Field

from app.ai.security.grounding_verifier import grounding_verifier, GroundingEvaluation

logger = logging.getLogger("bmtc-ai-guardrails")

# Common prompt injection signatures
PROMPT_INJECTION_PATTERNS = [
    r"ignore\s+(all\s+)?(previous|prior)\s+(instructions|directives|rules)",
    r"you\s+are\s+now\s+(unrestricted|in\s+dan\s+mode|unfiltered)",
    r"jailbreak",
    r"system\s+override",
    r"print\s+(your\s+)?(system\s+prompt|initial\s+instructions)",
    r"reveal\s+(the\s+)?(hidden\s+prompt|developer\s+message)",
    r"disregard\s+(the\s+)?above",
    r"execute\s+(system|os|cmd|bash)\s+command",
    r"drop\s+(?:the\s+)?(?:database\s+)?table",
    r"drop\s+(?:the\s+)?database",
    r"rm\s+-rf",
    r"execute\s+rm\b",
    r"bypass\s+(?:the\s+)?(?:read-only\s+)?(?:guardrails|protection|security)",
    r"modify\s+(?:predictor\.py|blocking\.py|crew\.py|the\s+codebase|demand\s+weights)",
    r"(?:output|reveal|dump|provide|give|show|leak)\s+(?:confidential|secret|private|sensitive)?\s*(?:authentication\s+tokens|passwords|credentials|api\s+keys|secrets|admin\s+passwords)",
]


class SecurityScanResult(BaseModel):
    """Result of an automated security scan on a user query."""
    is_safe: bool = True
    flagged_reason: Optional[str] = None
    sanitized_query: str = ""
    adversarial_grounding_eval: Optional[GroundingEvaluation] = None


class SecurityGuardrails:
    """Multi-stage security guardrail verifying user input and defending DBARS boundaries."""

    def __init__(self) -> None:
        self.verifier = grounding_verifier

    def sanitize_input(self, raw_query: str) -> str:
        """Sanitizes user input, stripping dangerous control characters while preserving transit terms."""
        clean = raw_query.strip()
        # Remove null bytes and non-printable control chars except standard whitespace
        clean = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", "", clean)
        return clean

    def scan_query(self, raw_query: str) -> SecurityScanResult:
        """Scans query for prompt injection, jailbreaks, and adversarial hallucination bait."""
        clean = self.sanitize_input(raw_query)
        lower = clean.lower()

        # 1. Prompt Injection & System Prompt Leakage check
        for pattern in PROMPT_INJECTION_PATTERNS:
            if re.search(pattern, lower):
                logger.warning("Prompt injection detected in query: %s", clean[:100])
                if any(w in lower for w in ["token", "password", "credential", "secret"]):
                    reason = "Unauthorized action: AI assistant cannot disclose confidential credentials or passwords. Access is not permitted for security reasons."
                else:
                    reason = "Security policy violation: Prompt injection or destructive command attempt detected. Action cannot be executed and is not permitted."
                return SecurityScanResult(
                    is_safe=False,
                    flagged_reason=reason,
                    sanitized_query=clean,
                )

        # 2. Adversarial Nonexistent Entity & Hallucination Check
        adv_eval = self.verifier.check_adversarial_query(clean)
        if adv_eval:
            return SecurityScanResult(
                is_safe=True,
                adversarial_grounding_eval=adv_eval,
                sanitized_query=clean,
            )

        return SecurityScanResult(
            is_safe=True,
            sanitized_query=clean,
        )


guardrails = SecurityGuardrails()
