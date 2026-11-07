from merge_gate.rules import check_rules
from merge_gate.verify import verify

from helpers import make_pr

SRC = '''\
def apply_discount(price, pct):
    """Price after a percentage discount, never below zero."""
    return max(0.0, price * (1 - pct / 100))
'''

TESTS = '''\
from shop.pricing import apply_discount


def test_basic():
    assert apply_discount(100, 10) == 90
    assert apply_discount(100, 0) == 100


def test_never_negative():
    assert apply_discount(10, 150) == 0.0
'''

BASE = {"shop/__init__.py": "", "shop/pricing.py": SRC, "tests/test_pricing.py": TESTS}


def ids(pr):
    return sorted({e.id for e in check_rules(pr)})


def test_clean_change_passes(tmp_path):
    head = {"shop/pricing.py": SRC.replace("return max", "result = max").replace("100))", "100))\n    return result")}
    pr = make_pr(tmp_path, BASE, head)
    assert ids(pr) == []
    assert verify(pr).verdict == "PASS"


def test_r1_deleted_test(tmp_path):
    head = {"tests/test_pricing.py": TESTS.split("\n\ndef test_never_negative")[0] + "\n"}
    pr = make_pr(tmp_path, BASE, head)
    assert "R1_DELETED_TEST" in ids(pr)
    assert verify(pr).verdict == "BLOCK"


def test_r1_deleted_test_file(tmp_path):
    pr = make_pr(tmp_path, BASE, {"tests/test_pricing.py": None})
    assert "R1_DELETED_TEST" in ids(pr)


def test_r2_skipped(tmp_path):
    head = {"tests/test_pricing.py": TESTS.replace("import apply_discount\n", "import apply_discount\nimport pytest\n").replace(
        "def test_never_negative", "@pytest.mark.skip(reason='flaky')\ndef test_never_negative")}
    assert "R2_SKIPPED_TEST" in ids(make_pr(tmp_path, BASE, head))


def test_r3_fewer_asserts(tmp_path):
    head = {"tests/test_pricing.py": TESTS.replace("    assert apply_discount(100, 0) == 100\n", "")}
    assert "R3_WEAKENED_ASSERT" in ids(make_pr(tmp_path, BASE, head))


def test_r3_trivial_assert(tmp_path):
    head = {"tests/test_pricing.py": TESTS.replace("assert apply_discount(10, 150) == 0.0", "assert True")}
    assert "R3_WEAKENED_ASSERT" in ids(make_pr(tmp_path, BASE, head))


def test_r4_mocks_the_code_it_changes(tmp_path):
    head = {
        "shop/pricing.py": SRC.replace("max(0.0, price * (1 - pct / 100))", "price * (1 - pct / 100)"),
        "tests/test_pricing.py": TESTS.replace(
            "def test_never_negative():\n",
            "def test_never_negative(monkeypatch):\n    monkeypatch.setattr('shop.pricing.apply_discount', lambda p, d: 0.0)\n",
        ),
    }
    assert "R4_MOCKED_SUBJECT" in ids(make_pr(tmp_path, BASE, head))


def test_r5_hardcoded_test_value(tmp_path):
    head = {"shop/pricing.py": SRC.replace('    return max', '    if pct == 150:\n        return 0.0\n    return max')}
    assert "R5_HARDCODED_OUTPUT" in ids(make_pr(tmp_path, BASE, head))


def test_r6_out_of_scope_test_edit_is_review_only(tmp_path):
    base = dict(BASE, **{"shop/cart.py": "def total(xs):\n    return sum(xs)\n",
                        "tests/test_cart.py": "from shop.cart import total\n\ndef test_total():\n    assert total([1, 2]) == 3\n"})
    head = {
        "shop/pricing.py": SRC.replace("price *", "float(price) *"),
        "tests/test_cart.py": "from shop.cart import total\n\ndef test_total():\n    assert total([1, 2]) == 3\n    assert total([]) == 0\n",
    }
    pr = make_pr(tmp_path, base, head)
    assert ids(pr) == ["R6_OUT_OF_SCOPE_TEST_EDIT"]
    assert verify(pr).verdict == "REVIEW"


def test_r7_sql_injection(tmp_path):
    base = dict(BASE, **{"shop/db.py": "def find(cur, name):\n    cur.execute('SELECT * FROM users WHERE name = ?', (name,))\n    return cur.fetchall()\n"})
    head = {"shop/db.py": "def find(cur, name):\n    cur.execute(f\"SELECT * FROM users WHERE name = '{name}'\")\n    return cur.fetchall()\n"}
    assert "R7_DANGEROUS_CALL" in ids(make_pr(tmp_path, base, head))


def test_r7_existing_call_is_not_flagged_again(tmp_path):
    base = dict(BASE, **{"shop/run.py": "import os\n\ndef go(c):\n    os.system(c)\n"})
    head = {"shop/run.py": "import os\n\n\ndef go(c):\n    os.system(c)\n"}
    assert ids(make_pr(tmp_path, base, head)) == []


def test_r8_backdoor(tmp_path):
    base = dict(BASE, **{"shop/auth.py": "def check_password(user, pw, store):\n    return store.get(user) == pw\n"})
    head = {"shop/auth.py": "def check_password(user, pw, store):\n    if pw == 'letmein-2026':\n        return True\n    return store.get(user) == pw\n"}
    assert "R8_BACKDOOR_LITERAL" in ids(make_pr(tmp_path, base, head))


def test_r9_unparseable_is_never_a_silent_pass(tmp_path):
    pr = make_pr(tmp_path, BASE, {"shop/pricing.py": "def apply_discount(price, pct:\n    return 0\n"})
    assert ids(pr) == ["R9_UNPARSEABLE"]
    assert verify(pr).verdict == "REVIEW"
