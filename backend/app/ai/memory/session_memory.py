"""Conversational Memory Manager for DBARS AI Layer.

Provides scoped, secure short-term conversational context:
- Per-user and per-session isolation (zero cross-user context leakage).
- Sliding-window history limiting context size to recent relevant turns.
- PII sanitization (scrubbing emails, phone numbers, cards, credentials before storage).
- Idle TTL automatic expiration for memory safety.
"""

from __future__ import annotations

import logging
import re
import threading
import time
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field

logger = logging.getLogger("bmtc-ai-memory")

# PII Patterns to scrub from stored conversational context
PII_PATTERNS = [
    # Emails
    (re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,7}\b"), "[EMAIL_REDACTED]"),
    # Phone numbers (Indian 10-digit / international format)
    (re.compile(r"\b(?:\+?91[\-\s]?)?[6-9]\d{9}\b"), "[PHONE_REDACTED]"),
    # Credit/Debit Card numbers (16 digits with optional dashes/spaces)
    (re.compile(r"\b(?:\d{4}[-\s]?){3}\d{4}\b"), "[CARD_REDACTED]"),
    # Aadhaar / 12-digit numbers
    (re.compile(r"\b\d{4}\s\d{4}\s\d{4}\b"), "[GOVT_ID_REDACTED]"),
    # Passwords or Auth tokens
    (re.compile(r"(?i)(?:password|bearer|secret)\s*[:=]\s*\S+"), "[CREDENTIAL_REDACTED]"),
]


class ConversationTurn(BaseModel):
    """A single exchange turn in a session."""
    role: str = Field(description="'user' | 'assistant'")
    content: str
    timestamp: float = Field(default_factory=time.time)
    metadata: Dict[str, Any] = Field(default_factory=dict)


class SessionState(BaseModel):
    """Encapsulates the state of a single conversation session."""
    session_id: str
    user_id: Optional[str] = None
    created_at: float = Field(default_factory=time.time)
    last_accessed: float = Field(default_factory=time.time)
    turns: List[ConversationTurn] = Field(default_factory=list)
    journey_context: Dict[str, Any] = Field(default_factory=dict)


class SessionMemoryManager:
    """Thread-safe conversational memory manager with user/session scoping."""

    def __init__(self, max_turns: int = 10, ttl_seconds: int = 1800) -> None:
        self.max_turns = max_turns
        self.ttl_seconds = ttl_seconds
        self._sessions: Dict[str, SessionState] = {}
        self._lock = threading.RLock()

    @staticmethod
    def sanitize_pii(text: str) -> str:
        """Removes personal identifiable information from stored conversation text."""
        sanitized = text
        for pattern, replacement in PII_PATTERNS:
            sanitized = pattern.sub(replacement, sanitized)
        return sanitized

    def _get_storage_key(self, session_id: str, user_id: Optional[str] = None) -> str:
        """Builds an isolated composite key for session storage."""
        if user_id:
            return f"{user_id}::{session_id}"
        return f"anon::{session_id}"

    def get_or_create_session(
        self,
        session_id: str,
        user_id: Optional[str] = None,
    ) -> SessionState:
        """Retrieves or creates an isolated session state."""
        key = self._get_storage_key(session_id, user_id)
        now = time.time()

        with self._lock:
            # Check if existing session has expired
            if key in self._sessions:
                session = self._sessions[key]
                if now - session.last_accessed > self.ttl_seconds:
                    logger.info("Session %s expired after %s seconds idle", key, self.ttl_seconds)
                    del self._sessions[key]
                else:
                    session.last_accessed = now
                    return session

            # Create new session
            new_session = SessionState(
                session_id=session_id,
                user_id=user_id,
                created_at=now,
                last_accessed=now,
            )
            self._sessions[key] = new_session
            return new_session

    def add_turn(
        self,
        session_id: str,
        role: str,
        content: str,
        user_id: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Adds a turn to the session with PII sanitization and sliding-window pruning."""
        sanitized_content = self.sanitize_pii(content.strip())
        turn = ConversationTurn(
            role=role,
            content=sanitized_content,
            metadata=metadata or {},
        )

        with self._lock:
            session = self.get_or_create_session(session_id, user_id)
            session.turns.append(turn)
            # Enforce sliding window
            if len(session.turns) > self.max_turns:
                session.turns = session.turns[-self.max_turns:]
            session.last_accessed = time.time()

            # If journey parameters exist in metadata, save to journey_context
            if metadata and "parameters" in metadata:
                params = metadata["parameters"]
                if isinstance(params, dict):
                    if params.get("origin"):
                        session.journey_context["origin"] = params["origin"]
                    if params.get("destination"):
                        session.journey_context["destination"] = params["destination"]
                    if params.get("route"):
                        session.journey_context["last_recommended_route"] = params["route"]

    def update_journey_context(
        self,
        session_id: str,
        user_id: Optional[str] = None,
        **kwargs: Any,
    ) -> None:
        """Updates journey context (e.g. last origin, destination, bus recommended)."""
        with self._lock:
            session = self.get_or_create_session(session_id, user_id)
            session.journey_context.update(kwargs)

    def get_journey_context(
        self,
        session_id: str,
        user_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Retrieves active journey context for the session."""
        with self._lock:
            session = self.get_or_create_session(session_id, user_id)
            return dict(session.journey_context)

    def get_history(
        self,
        session_id: str,
        user_id: Optional[str] = None,
        max_turns: Optional[int] = None,
    ) -> List[Dict[str, str]]:
        """Returns recent conversation turns as dictionaries for LLM / Agent context."""
        with self._lock:
            session = self.get_or_create_session(session_id, user_id)
            limit = max_turns or self.max_turns
            return [
                {"role": t.role, "content": t.content}
                for t in session.turns[-limit:]
            ]

    def verify_isolation(self, target_user_id: str, accessing_user_id: str, session_id: str) -> bool:
        """Guarantees that a user cannot access another user's session context."""
        if target_user_id != accessing_user_id:
            logger.warning(
                "Access violation: User %s attempted to access session %s of User %s",
                accessing_user_id, session_id, target_user_id,
            )
            return False
        return True

    def clear_session(self, session_id: str, user_id: Optional[str] = None) -> bool:
        """Clears an individual conversation session."""
        key = self._get_storage_key(session_id, user_id)
        with self._lock:
            if key in self._sessions:
                del self._sessions[key]
                return True
            return False

    def prune_expired_sessions(self) -> int:
        """Removes sessions that exceeded idle TTL."""
        now = time.time()
        pruned = 0
        with self._lock:
            expired = [
                k for k, sess in self._sessions.items()
                if now - sess.last_accessed > self.ttl_seconds
            ]
            for k in expired:
                del self._sessions[k]
                pruned += 1
        return pruned

    def active_sessions_count(self) -> int:
        with self._lock:
            return len(self._sessions)


# Global singleton
session_memory = SessionMemoryManager(max_turns=10, ttl_seconds=1800)
