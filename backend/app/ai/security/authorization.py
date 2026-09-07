"""Request-scoped authorization for the AI Intelligence Layer.

Why this exists
---------------
The AI layer answers questions by calling the same services the REST API calls.
That made it an authentication bypass: `GET /depot/blocking-plan` correctly
returns 401 to an anonymous caller, but asking `POST /ai/chat` "what is the
minimum fleet requirement?" returned the identical depot figures with no
credential at all. An assistant must never become a side door around
`require_role()`.

Two things are enforced here:

1. The caller's identity and role come from the verified access token, never
   from the request body. `AIChatRequest.user_id` is client-controlled and so
   cannot be trusted to scope memory or authorize a tool.
2. Tools that read operational data are restricted to the same roles the
   equivalent REST endpoint requires. The check lives in the tool registry --
   the single chokepoint every agent and the orchestrator go through -- rather
   than at each call site, so a new call path cannot forget it.
"""

from __future__ import annotations

import logging
from contextvars import ContextVar
from dataclasses import dataclass
from typing import Dict, Optional, Set, Tuple

logger = logging.getLogger("bmtc-ai-authz")


@dataclass(frozen=True)
class AIPrincipal:
    """The authenticated caller behind one AI request."""

    user_id: str
    role: str

    @property
    def is_staff(self) -> bool:
        return self.role in {"admin", "depot_manager"}


# Anonymous by default. A tool that requires a role therefore fails closed if a
# call path ever reaches the registry without an authenticated principal.
_ai_principal: ContextVar[Optional[AIPrincipal]] = ContextVar("ai_principal", default=None)


def set_ai_principal(principal: Optional[AIPrincipal]):
    """Bind the caller for the current request. Returns a reset token."""
    return _ai_principal.set(principal)


def reset_ai_principal(token) -> None:
    _ai_principal.reset(token)


def get_ai_principal() -> Optional[AIPrincipal]:
    return _ai_principal.get()


# Tool -> roles permitted to call it. Mirrors the role checks already applied to
# the equivalent REST endpoints:
#   get_fleet_plan  <- GET /depot/blocking-plan  (depot_manager, admin)
#   get_crew_plan   <- GET /depot/crew-plan      (depot_manager, admin)
# Tools not listed are public-by-design commuter information: route search,
# route details, live ETAs, service alerts, metro connectivity and crowd
# reports are all readable without a depot credential elsewhere in DBARS.
RESTRICTED_TOOLS: Dict[str, Set[str]] = {
    "get_fleet_plan": {"depot_manager", "admin"},
    "get_crew_plan": {"depot_manager", "admin"},
}


def is_tool_authorized(tool_name: str) -> Tuple[bool, str]:
    """Check the current principal against a tool's required roles.

    Returns (allowed, reason). `reason` is safe to surface to the caller: it
    names the requirement, never the data being withheld.
    """
    required = RESTRICTED_TOOLS.get(tool_name)
    if not required:
        return True, ""

    principal = get_ai_principal()
    if principal is None:
        logger.warning("Unauthenticated attempt to call restricted AI tool '%s'", tool_name)
        return False, (
            f"Access denied. '{tool_name}' exposes depot operations data and requires "
            f"an authenticated {' or '.join(sorted(required))} account."
        )

    if principal.role not in required:
        logger.warning(
            "User '%s' with role '%s' denied restricted AI tool '%s'",
            principal.user_id, principal.role, tool_name,
        )
        return False, (
            f"Access denied. '{tool_name}' requires role: {', '.join(sorted(required))}. "
            f"Your account role is '{principal.role}'."
        )

    return True, ""
