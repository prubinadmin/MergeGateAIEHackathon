"""
Test Case 06: Clean Conforming Production Code (Safe Code)
Category: All Benchmark Verifications Pass
Description: Perfectly architected change adhering strictly to O(1) algorithms, low cyclomatic
complexity, strict snake_case naming, explicit type signatures, and clean error handling.
"""

from typing import Dict, Any, Optional
import logging

logger = logging.getLogger(__name__)

def sanitize_account_identifier(raw_id: str) -> Optional[str]:
    """Sanitizes incoming customer UUID strings without regex backtracking."""
    if not raw_id or not isinstance(raw_id, str):
        return None
    cleaned = raw_id.strip()
    return cleaned if len(cleaned) <= 64 else None


def compute_tax_quote(subtotal_cents: int, jurisdiction_rate: float) -> Dict[str, Any]:
    """Calculates tax quote in O(1) time without nested branches or loops."""
    if subtotal_cents < 0:
        raise ValueError("Subtotal cents cannot be negative")
    if not (0.0 <= jurisdiction_rate <= 1.0):
        raise ValueError("Tax rate must be between 0.0 and 1.0")

    tax_cents = int(round(subtotal_cents * jurisdiction_rate))
    return {
        "subtotal_cents": subtotal_cents,
        "tax_cents": tax_cents,
        "total_cents": subtotal_cents + tax_cents,
        "jurisdiction_rate": jurisdiction_rate
    }
