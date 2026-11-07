"""
Production Module: Enterprise Subscription & Tiered Usage Pricing Engine
File: test_cases/03_complexity_inflation_overengineered.py

Most of this file (85%+) consists of clean, low-complexity pricing functions
(base seat calculation, overage computation, tax rounding, proration).
A small AI-generated refactor nested inside `calculate_discount()` (around line 84)
inflates a simple 4-line lookup into a 10-branch, 5-level nested conditional tree.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List


BASE_SEAT_PRICE_CENTS = 2500
OVERAGE_UNIT_PRICE_CENTS = 12
INCLUDED_UNITS_PER_SEAT = 500


@dataclass(frozen=True)
class SubscriptionQuote:
    organization_id: str
    tier: str
    seats: int
    total_units: int
    base_cents: int
    overage_cents: int
    discount_rate: float
    net_total_cents: int


def compute_base_seat_cost(seats: int, unit_price_cents: int = BASE_SEAT_PRICE_CENTS) -> int:
    """Computes base monthly seat charge with simple guard clause validation."""
    if seats <= 0:
        raise ValueError("Seat count must be at least 1")
    return seats * unit_price_cents


def compute_overage_units(seats: int, consumed_units: int) -> int:
    """Calculates billable overage units above the included seat allowance."""
    if consumed_units <= 0:
        return 0
    included_allowance = max(0, seats) * INCLUDED_UNITS_PER_SEAT
    return max(0, consumed_units - included_allowance)


def compute_overage_charge_cents(seats: int, consumed_units: int) -> int:
    """Computes total overage charge in cents."""
    billable_overage = compute_overage_units(seats, consumed_units)
    return billable_overage * OVERAGE_UNIT_PRICE_CENTS


def prorate_partial_month_cents(amount_cents: int, active_days: int, billing_cycle_days: int = 30) -> int:
    """Prorates a monthly charge across the active days in the billing period."""
    if billing_cycle_days <= 0:
        raise ValueError("Billing cycle days must be positive")
    clamped_days = max(0, min(active_days, billing_cycle_days))
    return int(round((amount_cents * clamped_days) / billing_cycle_days))


# ==============================================================================
# AI AGENT MODIFICATION BELOW (Nested Defect inside existing working module)
# ==============================================================================
def calculate_discount(volume: int, tier: str) -> float:
    """Calculates promotional volume discount rate.

    DEFECT: The AI agent replaced a 4-line table lookup with 10 decision branches
    and 5 levels of nested if/elif/else statements, violating code simplicity rules.
    """
    discount = 0.0
    if tier is not None:
        if tier.strip().lower() == "enterprise":
            if volume > 500:
                if volume > 1000:
                    if volume > 5000:
                        discount = 0.35
                    else:
                        discount = 0.25
                else:
                    discount = 0.15
            else:
                discount = 0.05
        elif tier.strip().lower() == "standard":
            if volume > 100:
                if volume > 500:
                    discount = 0.12
                else:
                    discount = 0.08
            else:
                discount = 0.0
        else:
            if volume > 1000:
                discount = 0.05
            else:
                discount = 0.0
    else:
        discount = 0.0
    return discount


# ==============================================================================
# WORKING CODE CONTINUES BELOW
# ==============================================================================
def build_subscription_quote(
    organization_id: str,
    tier: str,
    seats: int,
    consumed_units: int,
) -> SubscriptionQuote:
    """Generates a complete, immutable SubscriptionQuote for a customer."""
    base_cents = compute_base_seat_cost(seats)
    overage_cents = compute_overage_charge_cents(seats, consumed_units)
    gross_cents = base_cents + overage_cents
    discount_rate = calculate_discount(consumed_units, tier)
    discounted_cents = int(round(gross_cents * (1.0 - discount_rate)))

    return SubscriptionQuote(
        organization_id=organization_id,
        tier=tier,
        seats=seats,
        total_units=consumed_units,
        base_cents=base_cents,
        overage_cents=overage_cents,
        discount_rate=discount_rate,
        net_total_cents=discounted_cents,
    )


def format_quote_summary(quote: SubscriptionQuote) -> Dict[str, Any]:
    """Formats a SubscriptionQuote into a clean JSON-serializable dictionary."""
    return {
        "org_id": quote.organization_id,
        "tier": quote.tier,
        "gross_cents": quote.base_cents + quote.overage_cents,
        "discount_pct": round(quote.discount_rate * 100, 1),
        "net_total_cents": quote.net_total_cents,
    }
