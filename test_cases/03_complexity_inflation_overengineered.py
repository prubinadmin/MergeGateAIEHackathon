"""
Test Case 03: Complexity Inflation & Over-Engineering (Unsafe AI Code)
Category: Code Simplicity & Cyclomatic Complexity Guard
Description: An AI agent refactored a clean 4-line pricing function into a convoluted
8-branch cyclomatic labyrinth with nested decision trees and unneeded state checks.
"""

from typing import Dict, Any

# BASE CODE:
# def calculate_discount(volume: int, tier: str) -> float:
#     if tier == "enterprise" and volume > 1000:
#         return 0.25
#     return 0.10 if volume > 100 else 0.0

# AI GENERATED CHANGE:
def calculate_discount(volume: int, tier: str) -> float:
    # DEFECT: Exploded cyclomatic complexity (+7 decision branches, 4 levels of nesting)
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
