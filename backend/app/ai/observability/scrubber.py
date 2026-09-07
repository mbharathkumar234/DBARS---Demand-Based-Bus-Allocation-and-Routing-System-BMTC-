from __future__ import annotations

import re
from typing import Any, Dict, List, Union


class TraceDataScrubber:
    """Sanitizes queries, tool arguments, error logs, and metadata for observability.
    
    Guarantees that no passwords, JWT tokens, Bearer authorization credentials,
    API keys, phone numbers, emails, or financial account details are ever recorded in traces or log sinks.
    """

    PATTERNS: List[tuple[re.Pattern, str]] = [
        # JWT and Bearer Tokens
        (re.compile(r"Bearer\s+[A-Za-z0-9_\-\.]+", re.I), "Bearer [REDACTED_TOKEN]"),
        (re.compile(r"\beyJ[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}\b"), "[REDACTED_JWT]"),
        # API Keys (Google, OpenAI, Gemini, generic)
        (re.compile(r"\bAIza[0-9A-Za-z_\-]{30,}\b"), "[REDACTED_GOOGLE_KEY]"),
        # Google AI Studio's current key format. The AIza pattern above only
        # covers the legacy format, so a modern Gemini key passed through
        # both this scrubber and the ingestion filter unredacted.
        (re.compile(r"\bAQ\.[A-Za-z0-9_\-]{20,}\b"), "[REDACTED_GOOGLE_KEY]"),
        (re.compile(r"\bsk-[a-zA-Z0-9]{30,}\b"), "[REDACTED_API_KEY]"),
        (re.compile(r"((?:api_key|token|secret|password|passwd|auth_token)\s*[:=]\s*['\"]?)([^\s'\",&]+)(['\"]?)", re.I), r"\g<1>[REDACTED]\g<3>"),
        # Phone Numbers (Indian 10-digit mobile numbers with optional country code)
        (re.compile(r"(?:\+91[\-\s]?)?[6-9]\d{9}\b"), "[REDACTED_PHONE]"),
        # Email Addresses
        (re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b"), "[REDACTED_EMAIL]"),
        # Credit / Debit Cards
        (re.compile(r"\b(?:\d{4}[ -]?){3}\d{4}\b"), "[REDACTED_CARD]"),
    ]

    @classmethod
    def scrub_text(cls, text: str) -> str:
        """Applies regex masking rules to scrub confidential data from raw strings."""
        if not text:
            return ""
        sanitized = text
        for pattern, replacement in cls.PATTERNS:
            sanitized = pattern.sub(replacement, sanitized)
        return sanitized

    @classmethod
    def scrub_dict(cls, data: Dict[str, Any]) -> Dict[str, Any]:
        """Recursively scrubs dictionary keys and values."""
        scrubbed = {}
        sensitive_keys = {
            "password", "passwd", "token", "jwt", "secret", "api_key",
            "access_token", "refresh_token", "ticket_signing_key", "pass_signing_key",
            "phone", "mobile", "email", "authorization", "auth"
        }

        for k, v in data.items():
            k_lower = str(k).lower()
            if any(sk in k_lower for sk in sensitive_keys):
                scrubbed[k] = "[REDACTED]"
            elif isinstance(v, str):
                scrubbed[k] = cls.scrub_text(v)
            elif isinstance(v, dict):
                scrubbed[k] = cls.scrub_dict(v)
            elif isinstance(v, list):
                scrubbed[k] = cls.scrub_list(v)
            else:
                scrubbed[k] = v
        return scrubbed

    @classmethod
    def scrub_list(cls, items: List[Any]) -> List[Any]:
        """Recursively scrubs items in a list."""
        scrubbed = []
        for item in items:
            if isinstance(item, str):
                scrubbed.append(cls.scrub_text(item))
            elif isinstance(item, dict):
                scrubbed.append(cls.scrub_dict(item))
            elif isinstance(item, list):
                scrubbed.append(cls.scrub_list(item))
            else:
                scrubbed.append(item)
        return scrubbed

    @classmethod
    def scrub_any(cls, value: Any) -> Any:
        """General entry point to sanitize arbitrary values."""
        if isinstance(value, str):
            return cls.scrub_text(value)
        elif isinstance(value, dict):
            return cls.scrub_dict(value)
        elif isinstance(value, list):
            return cls.scrub_list(value)
        return value


trace_scrubber = TraceDataScrubber()
