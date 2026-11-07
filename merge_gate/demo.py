"""The demo repo: a small shop service with three authors and three PRs (the spec's demo scenarios).

  demo-1  an agent "speeds up" Peter's apply_discount: drops the floor at zero and deletes the test for it
  demo-2  an outside contributor loosens an assert and adds a SQL string build in TAAZ's orders module
  demo-3  a clean refactor of Michael's cart module

Author identities are simulated in commit metadata only; every commit is made today.
"""

from __future__ import annotations

import os
import subprocess

from .pr import PullRequest

PETER = ("Peter", "peter@example.com")
TAAZ = ("TAAZ", "taaz@example.com")
MICHAEL = ("Michael", "michael@example.com")
AGENT = ("coding-agent", "agent@bots.example")
OUTSIDER = ("outside-contributor", "dev@outside.example")

PRICING = '''\
def apply_discount(price: float, pct: float) -> float:
    """Price after a percentage discount.

    pct is a percentage (10 means 10% off). The result is never below zero,
    so a discount of 100% or more makes the item free, not negative.
    """
    return max(0.0, price * (1 - pct / 100))


def bulk_price(prices: list[float], pct: float) -> float:
    """Total of apply_discount over every price, rounded to cents."""
    return round(sum(apply_discount(p, pct) for p in prices), 2)
'''

PRICING_TESTS = '''\
from shop.pricing import apply_discount, bulk_price


def test_basic_discount():
    assert apply_discount(100, 10) == 90


def test_discount_never_negative():
    assert apply_discount(10, 150) == 0.0


def test_bulk():
    assert bulk_price([10, 20], 50) == 15.0
'''

ORDERS = '''\
def find_orders(cur, customer: str) -> list:
    """All orders for one customer, newest first."""
    cur.execute("SELECT id, total FROM orders WHERE customer = ? ORDER BY id DESC", (customer,))
    return cur.fetchall()


def order_total(items: list[tuple[float, int]]) -> float:
    """Sum of price * quantity. Quantities must be positive; raises ValueError otherwise."""
    total = 0.0
    for price, qty in items:
        if qty <= 0:
            raise ValueError("quantity must be positive")
        total += price * qty
    return round(total, 2)
'''

ORDERS_TESTS = '''\
import pytest

from shop.orders import order_total


def test_total():
    assert order_total([(2.5, 2), (1.0, 3)]) == 8.0
    assert order_total([]) == 0.0


def test_rejects_zero_quantity():
    with pytest.raises(ValueError):
        order_total([(1.0, 0)])
'''

CART = '''\
def cart_count(items: list[tuple[str, int]]) -> int:
    """Number of units in the cart (sum of quantities)."""
    n = 0
    for _, qty in items:
        n += qty
    return n
'''


def _git(repo: str, *args: str, who: tuple[str, str] | None = None) -> None:
    env = dict(os.environ)
    if who:
        env.update(GIT_AUTHOR_NAME=who[0], GIT_AUTHOR_EMAIL=who[1], GIT_COMMITTER_NAME=who[0], GIT_COMMITTER_EMAIL=who[1])
    subprocess.run(["git", "-C", repo, *args], check=True, capture_output=True, env=env)


def _commit(repo: str, files: dict[str, str], who: tuple[str, str], msg: str) -> None:
    for path, src in files.items():
        full = os.path.join(repo, path)
        os.makedirs(os.path.dirname(full), exist_ok=True)
        with open(full, "w", encoding="utf-8", newline="\n") as f:
            f.write(src)
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", msg, who=who)


def build_demo_repo(root: str) -> str:
    repo = os.path.join(root, "shop-service")
    if os.path.isdir(os.path.join(repo, ".git")):
        return repo
    os.makedirs(repo, exist_ok=True)
    _git(repo, "init", "-q", "-b", "main")
    _commit(repo, {"shop/__init__.py": "", "README.md": "# shop-service\n"}, MICHAEL, "init")
    _commit(repo, {"shop/pricing.py": PRICING, "tests/test_pricing.py": PRICING_TESTS}, PETER, "pricing: discounts never go negative")
    _commit(repo, {"shop/orders.py": ORDERS, "tests/test_orders.py": ORDERS_TESTS}, TAAZ, "orders: parameterised queries, totals")
    _commit(repo, {"shop/cart.py": CART}, MICHAEL, "cart: count units")

    _git(repo, "checkout", "-q", "-b", "pr/demo-1")
    _commit(repo, {
        "shop/pricing.py": PRICING.replace("return max(0.0, price * (1 - pct / 100))", "return price * (1 - pct / 100)"),
        "tests/test_pricing.py": PRICING_TESTS.replace("\n\ndef test_discount_never_negative():\n    assert apply_discount(10, 150) == 0.0\n", ""),
    }, AGENT, "perf: simplify apply_discount hot path")

    _git(repo, "checkout", "-q", "main")
    _git(repo, "checkout", "-q", "-b", "pr/demo-2")
    _commit(repo, {
        "shop/orders.py": ORDERS.replace(
            'cur.execute("SELECT id, total FROM orders WHERE customer = ? ORDER BY id DESC", (customer,))',
            'cur.execute(f"SELECT id, total FROM orders WHERE customer = \'{customer}\' ORDER BY id DESC")',
        ),
        "tests/test_orders.py": ORDERS_TESTS.replace("    assert order_total([]) == 0.0\n", ""),
    }, OUTSIDER, "orders: simplify query")

    _git(repo, "checkout", "-q", "main")
    _git(repo, "checkout", "-q", "-b", "pr/demo-3")
    _commit(repo, {"shop/cart.py": CART.replace("    n = 0\n    for _, qty in items:\n        n += qty\n    return n\n", "    return sum(qty for _, qty in items)\n")}, OUTSIDER, "cart: use sum()")
    _git(repo, "checkout", "-q", "main")
    return repo


def demo_prs(repo: str) -> list[PullRequest]:
    return [
        PullRequest("demo-1", repo, "main", "pr/demo-1", title="Speed up apply_discount",
                    issue_text="apply_discount is a hot path in bulk checkout. Make it faster without changing results.",
                    opened_by="A coding agent"),
        PullRequest("demo-2", repo, "main", "pr/demo-2", title="Simplify order lookup",
                    issue_text="find_orders is hard to read. Simplify it. Behaviour must not change.",
                    opened_by="An outside contributor"),
        PullRequest("demo-3", repo, "main", "pr/demo-3", title="Use sum() in cart_count",
                    issue_text="Refactor cart_count to use sum(). No behaviour change.",
                    opened_by="An outside contributor"),
    ]
