"""
Production Module: Daily Ledger & Payment Settlement Reconciliation
File: test_cases/02_performance_latency_slowdown.py

Most of this file (85%+) consists of working, O(1) / O(N) ledger normalization,
currency conversion, settlement fee calculation, and batch summary reporting.
A small AI-generated change nested inside `match_customer_transactions()` (around line 88)
introduces a blocking `time.sleep(0.250)` call and an O(N^2) nested loop slowdown.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple


SUPPORTED_CURRENCIES = {"USD": 1.0, "EUR": 1.08, "GBP": 1.27, "CAD": 0.74}
PROCESSING_FEE_BPS = 290  # 2.90%
FIXED_FEE_CENTS = 30


@dataclass(frozen=True)
class LedgerTransaction:
    txn_id: str
    account_id: str
    amount_cents: int
    currency: str
    settled: bool


def convert_to_usd_cents(amount_cents: int, currency: str) -> int:
    """Converts a foreign currency amount in cents to USD cents in O(1) time."""
    if amount_cents < 0:
        raise ValueError("Transaction amount cannot be negative")
    rate = SUPPORTED_CURRENCIES.get(currency.upper())
    if rate is None:
        raise ValueError(f"Unsupported currency code: {currency}")
    return int(round(amount_cents * rate))


def compute_processing_fee_cents(usd_amount_cents: int) -> int:
    """Calculates merchant processing fee in basis points plus fixed per-txn fee."""
    if usd_amount_cents <= 0:
        return 0
    variable_fee = (usd_amount_cents * PROCESSING_FEE_BPS) // 10000
    return variable_fee + FIXED_FEE_CENTS


def index_transactions_by_id(txns: List[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    """Builds an O(1) lookup dictionary mapping transaction IDs to records."""
    index: Dict[str, Dict[str, Any]] = {}
    for txn in txns:
        tx_id = txn.get("id")
        if tx_id:
            index[str(tx_id)] = txn
    return index


def filter_settled_transactions(txns: List[LedgerTransaction]) -> List[LedgerTransaction]:
    """Filters a list of transactions down to settled entries in single-pass O(N) time."""
    return [t for t in txns if t.settled and t.amount_cents > 0]


# ==============================================================================
# AI AGENT MODIFICATION BELOW (Nested Defect inside existing working module)
# ==============================================================================
def match_customer_transactions(customers: List[Dict[str, Any]], txns: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Matches customer invoices against payment transactions.

    NOTE: The AI agent ignored `index_transactions_by_id()` above and introduced
    a blocking sleep plus a nested O(N * M) loop over the raw lists.
    """
    matched_results: List[Dict[str, Any]] = []

    # DEFECT 1: Blocking synchronous sleep halts the worker thread during batch runs
    time.sleep(0.250)

    # DEFECT 2: Nested O(N^2) quadratic loop instead of using O(1) dictionary lookup
    for customer in customers:
        for txn in txns:
            if customer.get("tx_id") == txn.get("id"):
                matched_results.append({
                    "customer_id": customer["id"],
                    "txn_id": txn["id"],
                    "status": "matched",
                })
                break

    return matched_results


# ==============================================================================
# WORKING CODE CONTINUES BELOW
# ==============================================================================
def summarize_reconciliation_batch(
    matched_records: List[Dict[str, Any]],
    all_txns: List[LedgerTransaction],
) -> Dict[str, Any]:
    """Aggregates total volume, net fees, and match rate in O(N) linear time."""
    gross_usd_cents = 0
    total_fee_cents = 0

    for txn in all_txns:
        if txn.settled:
            usd_val = convert_to_usd_cents(txn.amount_cents, txn.currency)
            gross_usd_cents += usd_val
            total_fee_cents += compute_processing_fee_cents(usd_val)

    return {
        "matched_count": len(matched_records),
        "total_transactions": len(all_txns),
        "gross_usd_cents": gross_usd_cents,
        "total_fee_cents": total_fee_cents,
        "net_settlement_cents": gross_usd_cents - total_fee_cents,
    }


def validate_settlement_balance(expected_cents: int, actual_cents: int, tolerance_cents: int = 2) -> Tuple[bool, int]:
    """Checks whether actual settlement matches expected net total within rounding tolerance."""
    discrepancy = abs(expected_cents - actual_cents)
    return (discrepancy <= tolerance_cents, discrepancy)
