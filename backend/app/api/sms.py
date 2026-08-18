from __future__ import annotations

import asyncio
import base64
import hashlib
import hmac
import logging

from fastapi import APIRouter, Form, HTTPException, Request, status
from fastapi.responses import Response

from app.core.config import settings
from app.services.sms_service import (
    MIN_CONFIDENCE_FOR_CONFIDENT_REPLY,
    USAGE_REPLY,
    format_low_confidence_reply,
    format_sms_reply,
    parse_sms_query,
)
from app.services.analytics_service import log_event

logger = logging.getLogger("bmtc.sms")

router = APIRouter(prefix="/sms", tags=["sms"])


def _expected_twilio_signature(url: str, params: dict[str, str], auth_token: str) -> str:
    """Compute Twilio's X-Twilio-Signature for a request.

    Twilio's documented scheme: take the full request URL, append each POST
    parameter's name and value concatenated in lexicographic order by name,
    then HMAC-SHA1 the result with the account auth token and base64 it.
    See https://www.twilio.com/docs/usage/security#validating-requests.
    """
    payload = url + "".join(f"{key}{params[key]}" for key in sorted(params))
    digest = hmac.new(auth_token.encode(), payload.encode("utf-8"), hashlib.sha1).digest()
    return base64.b64encode(digest).decode()


async def _require_valid_twilio_signature(request: Request) -> None:
    """Reject any inbound webhook that Twilio did not actually send.

    Without this the endpoint is an open, unauthenticated door to the full
    prediction pipeline -- two O(n) stop-resolution scans plus a graph search
    per request -- that anyone on the internet can call at will.

    If TWILIO_AUTH_TOKEN isn't configured we cannot verify anything, so we
    refuse rather than fall open. POST /sms/query exists to exercise this same
    pipeline locally without a gateway, so this costs nothing in development.
    """
    auth_token = settings.twilio_auth_token
    if not auth_token:
        logger.warning("Rejected an /sms/webhook call: TWILIO_AUTH_TOKEN is not configured.")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="SMS webhook is not configured. Set TWILIO_AUTH_TOKEN to enable it.",
        )

    signature = request.headers.get("X-Twilio-Signature", "")
    if not signature:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Missing X-Twilio-Signature.")

    form = await request.form()
    params = {key: str(value) for key, value in form.items()}
    expected = _expected_twilio_signature(str(request.url), params, auth_token)
    if not hmac.compare_digest(signature, expected):
        logger.warning("Rejected an /sms/webhook call with an invalid X-Twilio-Signature.")
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Invalid X-Twilio-Signature.")


def _twiml(message: str) -> Response:
    # TwiML is Twilio's standard, stable, publicly documented XML response
    # format for SMS webhooks (https://www.twilio.com/docs/messaging/twiml).
    # Returning real TwiML here means this endpoint is genuinely ready to
    # receive traffic from a real Twilio phone number the moment one is
    # configured -- no rework needed, just pointing the number's webhook
    # URL at this endpoint. Escaping is minimal (XML-safe chars only
    # appear in route/stop names, which don't contain XML special
    # characters in this dataset) but kept simple and correct for the
    # characters that matter.
    escaped = message.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    xml = f'<?xml version="1.0" encoding="UTF-8"?><Response><Message>{escaped}</Message></Response>'
    return Response(content=xml, media_type="application/xml")


async def _answer_query(predictor, text: str) -> str:
    """Shared parse -> resolve -> confidence-check -> predict -> format
    pipeline used by both the real Twilio webhook and the JSON test
    endpoint below, so the two can never silently drift apart."""
    parsed = parse_sms_query(text)
    if not parsed:
        return USAGE_REPLY

    origin, destination = parsed
    await log_event("sms_query", {"matched_pattern": True})
    try:
        # Check resolution confidence BEFORE committing to an answer.
        # SMS has no visual context for a user to notice a bad match the
        # way the app UI does (which shows the interpreted stop names
        # alongside the result) -- so a low-confidence guess needs to say
        # so explicitly here, rather than state a route as fact. See
        # sms_service.py's format_low_confidence_reply docstring; this is
        # also why fuzzy matching itself was tightened this same session
        # (text.py's fuzzy_ratio) rather than just papering over the
        # symptom here.
        # Both of these are synchronous CPU work (_resolve_stop_name scans every
        # stop name; predict() is a graph search that can run for seconds). Run
        # off the event loop so an SMS query cannot stall every other request on
        # the worker -- same reason as POST /predict in api/routes.py.
        resolved_origin, origin_score = await asyncio.to_thread(
            predictor._resolve_stop_name, origin
        )
        resolved_destination, destination_score = await asyncio.to_thread(
            predictor._resolve_stop_name, destination
        )
        if origin_score < MIN_CONFIDENCE_FOR_CONFIDENT_REPLY or destination_score < MIN_CONFIDENCE_FOR_CONFIDENT_REPLY:
            await log_event("sms_low_confidence", {})
            return format_low_confidence_reply(
                text, resolved_origin, origin_score, resolved_destination, destination_score
            )

        prediction = await asyncio.to_thread(
            predictor.predict, resolved_origin, resolved_destination, 3
        )
    except ValueError as exc:
        return str(exc)
    except Exception:
        logger.exception("SMS prediction failed for %r -> %r", origin, destination)
        return "Something went wrong looking that up. Please try again."

    return format_sms_reply(prediction, resolved_origin, resolved_destination)


@router.post("/webhook")
async def sms_webhook(request: Request, Body: str = Form(...), From: str = Form(default="")) -> Response:
    """Real Twilio-compatible SMS webhook.

    This is the low-bandwidth/non-smartphone access channel: the same
    prediction engine the app uses, reachable by anyone who can send a
    text message, no app or data connection required. It has never been
    connected to a real phone number (that requires a paid SMS gateway
    account this project doesn't have) -- but the request/response
    contract here is real Twilio TwiML, not a placeholder, so connecting
    one is a configuration change, not a rewrite.

    Every request must carry a valid X-Twilio-Signature -- this endpoint runs
    the full (expensive) prediction pipeline, so it must not be callable by
    anyone who simply knows the URL.
    """
    await _require_valid_twilio_signature(request)
    logger.info("SMS query from %s: %r", From, Body)
    reply = await _answer_query(request.app.state.predictor, Body)
    return _twiml(reply)


@router.post("/query")
async def sms_query_test(request: Request, payload: dict) -> dict:
    """JSON equivalent of the webhook above, for testing/demoing the SMS
    experience without a real SMS gateway -- exercises the exact same
    parse -> predict -> format pipeline the real webhook uses."""
    text = str(payload.get("text", ""))
    reply = await _answer_query(request.app.state.predictor, text)
    return {"reply": reply}