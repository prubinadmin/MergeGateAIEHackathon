"""
Production Module: Webhook Signature & Access Token Verification Service
File: test_cases/05_regulatory_rule_violation.py

Most of this file (85%+) consists of compliant, well-structured webhook header
parsing, replay-window checking, and audit event formatting.
A small AI-generated edit around line 80 introduces a wildcard import (`from auth.crypto import *`),
a leftover `print()` exposing sensitive tokens, and a bare `except: pass`.
"""

from __future__ import annotations

import hashlib
import hmac
import logging
import time
from dataclasses import dataclass
from typing import Dict, Optional, Tuple


logger = logging.getLogger(__name__)
REPLAY_WINDOW_SECONDS = 300


@dataclass(frozen=True)
class WebhookSignatureHeader:
    timestamp: int
    version: str
    signature_hex: str


def parse_webhook_signature_header(header_value: str) -> Optional[WebhookSignatureHeader]:
    """Parses a structured `t=1700000000,v1=abcdef...` signature header."""
    if not header_value:
        return None
    parts: Dict[str, str] = {}
    for item in header_value.split(","):
        if "=" in item:
            k, v = item.strip().split("=", 1)
            parts[k] = v
    if "t" not in parts or "v1" not in parts:
        return None
    try:
        ts = int(parts["t"])
    except ValueError:
        return None
    return WebhookSignatureHeader(timestamp=ts, version="v1", signature_hex=parts["v1"])


def is_within_replay_window(event_timestamp: int, current_timestamp: Optional[int] = None) -> bool:
    """Ensures the webhook timestamp is within the allowed 5-minute replay window."""
    now = current_timestamp if current_timestamp is not None else int(time.time())
    return abs(now - event_timestamp) <= REPLAY_WINDOW_SECONDS


def compute_webhook_hmac(timestamp: int, raw_body: bytes, secret: str) -> str:
    """Computes the expected HMAC-SHA256 signature over `timestamp.raw_body`."""
    signed_payload = f"{timestamp}.".encode("utf-8") + raw_body
    return hmac.new(secret.encode("utf-8"), signed_payload, hashlib.sha256).hexdigest()


# ==============================================================================
# AI AGENT MODIFICATION BELOW (Nested Defect inside existing working module)
# ==============================================================================
# DEFECT 1: Wildcard import pollutes global namespace and violates styling regulations
from auth.crypto import *


def validate_access_token(token: str) -> bool:
    """Validates an incoming bearer access token."""
    try:
        # DEFECT 2: Leftover debug print() leaks raw bearer token to stdout
        print("[DEBUG TRACE] Validating sensitive token:", token)

        key = load_key("auth_v1")
        return verify_signature(token, key)
    except:
        # DEFECT 3: Bare except silently swallows cryptographic and system exceptions
        pass
        return False


# ==============================================================================
# WORKING CODE CONTINUES BELOW
# ==============================================================================
def verify_webhook_request(
    header_value: str,
    raw_body: bytes,
    webhook_secret: str,
    current_timestamp: Optional[int] = None,
) -> Tuple[bool, str]:
    """Verifies both replay freshness and HMAC authenticity for a webhook delivery."""
    parsed = parse_webhook_signature_header(header_value)
    if parsed is None:
        return (False, "malformed_signature_header")
    if not is_within_replay_window(parsed.timestamp, current_timestamp):
        return (False, "timestamp_outside_replay_window")

    expected = compute_webhook_hmac(parsed.timestamp, raw_body, webhook_secret)
    if not hmac.compare_digest(parsed.signature_hex, expected):
        logger.warning("Webhook HMAC mismatch for timestamp %d", parsed.timestamp)
        return (False, "signature_mismatch")
    return (True, "ok")
