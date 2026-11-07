"""
Production Module: Multi-Jurisdiction Tax & Invoice Compliance Calculator
File: test_cases/06_clean_conforming_code.py

100% of this file consists of clean, conforming production code:
- Valid syntax and explicit imports
- O(1) dictionary lookups and single-pass O(N) aggregations (no nested loops or blocking sleeps)
- Low cyclomatic complexity with flat guard clauses
- Strict PEP 8 snake_case naming and complete static type annotations
- Explicit exception handling and structured logging (no wildcard imports, bare excepts, or debug prints)
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Dict, List, Optional


logger = logging.getLogger(__name__)

JURISDICTION_TAX_RATES: Dict[str, float] = {
    "US-CA": 0.0825,
    "US-NY": 0.08875,
    "US-TX": 0.0625,
    "US-WA": 0.065,
    "EU-DE": 0.19,
    "UK-GB": 0.20,
}


@dataclass(frozen=True)
class TaxLineItem:
    sku: str
    subtotal_cents: int
    tax_exempt: bool = False


def sanitize_account_identifier(raw_id: str) -> Optional[str]:
    """Sanitizes incoming customer UUID strings without regex backtracking."""
    if not raw_id or not isinstance(raw_id, str):
        return None
    cleaned = raw_id.strip()
    return cleaned if 0 < len(cleaned) <= 64 else None


def resolve_jurisdiction_rate(jurisdiction_code: str) -> float:
    """Resolves the statutory tax rate for a jurisdiction in O(1) time."""
    if not jurisdiction_code:
        raise ValueError("Jurisdiction code must not be empty")
    normalized = jurisdiction_code.strip().upper()
    if normalized not in JURISDICTION_TAX_RATES:
        raise KeyError(f"Unsupported tax jurisdiction: {normalized}")
    return JURISDICTION_TAX_RATES[normalized]


def compute_tax_quote(subtotal_cents: int, jurisdiction_rate: float) -> Dict[str, Any]:
    """Calculates a tax quote in O(1) time without nested branches or loops."""
    if subtotal_cents < 0:
        raise ValueError("Subtotal cents cannot be negative")
    if not (0.0 <= jurisdiction_rate <= 1.0):
        raise ValueError("Tax rate must be between 0.0 and 1.0")

    tax_cents = int(round(subtotal_cents * jurisdiction_rate))
    return {
        "subtotal_cents": subtotal_cents,
        "tax_cents": tax_cents,
        "total_cents": subtotal_cents + tax_cents,
        "jurisdiction_rate": jurisdiction_rate,
    }


def calculate_invoice_totals(
    account_id: str,
    jurisdiction_code: str,
    items: List[TaxLineItem],
) -> Dict[str, Any]:
    """Aggregates taxable and tax-exempt line items in a single O(N) pass."""
    clean_account = sanitize_account_identifier(account_id)
    if clean_account is None:
        raise ValueError("Invalid account identifier")

    rate = resolve_jurisdiction_rate(jurisdiction_code)
    taxable_subtotal = 0
    exempt_subtotal = 0

    for item in items:
        if item.subtotal_cents < 0:
            raise ValueError(f"Negative line item amount on SKU {item.sku}")
        if item.tax_exempt:
            exempt_subtotal += item.subtotal_cents
        else:
            taxable_subtotal += item.subtotal_cents

    quote = compute_tax_quote(taxable_subtotal, rate)
    total_subtotal = taxable_subtotal + exempt_subtotal

    return {
        "account_id": clean_account,
        "jurisdiction": jurisdiction_code.strip().upper(),
        "subtotal_cents": total_subtotal,
        "taxable_subtotal_cents": taxable_subtotal,
        "exempt_subtotal_cents": exempt_subtotal,
        "tax_cents": quote["tax_cents"],
        "grand_total_cents": total_subtotal + quote["tax_cents"],
    }
