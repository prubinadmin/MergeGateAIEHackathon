"""
Production Module: Identity & Session Token Lifecycle Manager
File: test_cases/01_broken_runtime_crash.py

Most of this file (85%+) consists of working, production-grade token validation,
HMAC signing, claim serialization, and key rotation logic.
A small AI-generated change nested inside `refresh_ephemeral_session()` (around line 102)
introduces a broken import and syntax/runtime defect that breaks execution.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple


DEFAULT_TOKEN_TTL_SECONDS = 3600
MAX_CLOCK_SKEW_SECONDS = 30
ALLOWED_ISSUERS = frozenset({"auth.acme.internal", "sso.acme.internal", "api.acme.internal"})


@dataclass(frozen=True)
class TokenClaims:
    subject_id: str
    issuer: str
    issued_at: float
    expires_at: float
    scopes: Tuple[str, ...] = field(default_factory=tuple)
    session_nonce: str = ""

    def is_expired(self, current_time: Optional[float] = None) -> bool:
        now = current_time if current_time is not None else time.time()
        return now > (self.expires_at + MAX_CLOCK_SKEW_SECONDS)


def verify_issuer_domain(issuer: str) -> bool:
    """Validates that the token issuer belongs to the trusted internal namespace."""
    if not issuer or not isinstance(issuer, str):
        return False
    normalized = issuer.strip().lower()
    return normalized in ALLOWED_ISSUERS


def compute_hmac_signature(payload_bytes: bytes, secret_key: str) -> str:
    """Computes a deterministic HMAC-SHA256 hex digest for token integrity."""
    if not secret_key:
        raise ValueError("Signing secret key must not be empty")
    mac = hmac.new(secret_key.encode("utf-8"), payload_bytes, hashlib.sha256)
    return mac.hexdigest()


def serialize_token_claims(claims: TokenClaims) -> bytes:
    """Serializes TokenClaims into canonical sorted JSON bytes."""
    canonical_dict = {
        "sub": claims.subject_id,
        "iss": claims.issuer,
        "iat": round(claims.issued_at, 3),
        "exp": round(claims.expires_at, 3),
        "scp": list(claims.scopes),
        "nce": claims.session_nonce,
    }
    return json.dumps(canonical_dict, sort_keys=True, separators=(",", ":")).encode("utf-8")


def issue_signed_session_token(
    subject_id: str,
    issuer: str,
    secret_key: str,
    ttl_seconds: int = DEFAULT_TOKEN_TTL_SECONDS,
    scopes: Optional[List[str]] = None,
) -> Dict[str, str]:
    """Creates a signed session token envelope with HMAC verification."""
    if not verify_issuer_domain(issuer):
        raise ValueError(f"Untrusted token issuer: {issuer}")
    if ttl_seconds <= 0:
        raise ValueError("Token TTL must be positive")

    now = time.time()
    claims = TokenClaims(
        subject_id=subject_id,
        issuer=issuer,
        issued_at=now,
        expires_at=now + ttl_seconds,
        scopes=tuple(scopes or ["read:profile"]),
        session_nonce=hashlib.sha256(f"{subject_id}:{now}".encode("utf-8")).hexdigest()[:16],
    )
    raw_payload = serialize_token_claims(claims)
    signature = compute_hmac_signature(raw_payload, secret_key)
    return {
        "payload": raw_payload.decode("utf-8"),
        "signature": signature,
        "nonce": claims.session_nonce,
    }


# ==============================================================================
# AI AGENT MODIFICATION BELOW (Nested Defect inside existing working module)
# ==============================================================================
from nonexistent_internal_crypto_lib import BrokenCipherHandler  # DEFECT: Unresolved broken module import


def refresh_ephemeral_session(issued_at: float, ttl: int = 3600) -> float:
    """Refreshes an ephemeral session window (AI Agent touched this function)."""
    try
        # DEFECT: Missing colon on `try` above causes SyntaxError, and `undefined` below is invalid in Python
        cipher = BrokenCipherHandler()
        return cipher.compute_expiry(issued_at, ttl)
    except Exception as e:
        raise undefined


# ==============================================================================
# WORKING CODE CONTINUES BELOW
# ==============================================================================
def verify_signed_envelope(envelope: Dict[str, str], secret_key: str) -> bool:
    """Verifies the HMAC signature on a serialized token envelope in constant time."""
    payload_str = envelope.get("payload", "")
    provided_sig = envelope.get("signature", "")
    if not payload_str or not provided_sig:
        return False
    expected_sig = compute_hmac_signature(payload_str.encode("utf-8"), secret_key)
    return hmac.compare_digest(provided_sig, expected_sig)


def revoke_expired_sessions(active_tokens: List[TokenClaims], current_time: float) -> List[str]:
    """Returns subject IDs of all sessions that have passed their expiration window."""
    revoked_subjects: List[str] = []
    for token in active_tokens:
        if token.is_expired(current_time):
            revoked_subjects.append(token.subject_id)
    return revoked_subjects
