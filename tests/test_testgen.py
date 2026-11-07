"""testgen logic with the model replaced by fixed text: no network."""

from merge_gate import testgen
from merge_gate.testgen import _drop_tests, _extract_code, independent_check, public_interface

from helpers import make_pr

SRC = '''\
def apply_discount(price, pct):
    """Price after a percentage discount, never below zero."""
    return max(0.0, price * (1 - pct / 100))


def _helper():
    return 1
'''
BUGGY = SRC.replace("max(0.0, price * (1 - pct / 100))", "price * (1 - pct / 100)").replace(
    "never below zero", "fast path"
)

MODEL_OUTPUT = '''Here you go:
```python
import pytest


def test_invariant_basic():
    from shop.pricing import apply_discount
    assert apply_discount(100, 10) == pytest.approx(90)


def test_invariant_never_negative():
    from shop.pricing import apply_discount
    assert apply_discount(10, 150) == 0.0


def test_invariant_wrong_on_base():
    from shop.pricing import apply_discount
    assert apply_discount(100, 10) == 1234


def test_issue_new_rounding():
    from shop.pricing import apply_discount
    assert apply_discount(10, 33) == 6.7
```
'''


def _pr(tmp_path):
    return make_pr(tmp_path, {"shop/__init__.py": "", "shop/pricing.py": SRC}, {"shop/pricing.py": BUGGY},
                   issue="Make apply_discount faster.")


def test_interface_hides_bodies_and_keeps_base_docstrings(tmp_path):
    iface = public_interface(_pr(tmp_path))
    assert "def apply_discount(price, pct):" in iface
    assert "never below zero" in iface  # base docstring wins over the PR's rewrite
    assert "fast path" not in iface
    assert "max(0.0" not in iface and "_helper" not in iface


def test_extract_and_drop():
    code = _extract_code(MODEL_OUTPUT)
    assert "test_issue_new_rounding" in code
    assert "test_invariant_basic" not in _drop_tests(code, {"test_invariant_basic"})


def test_independent_check_classifies_failures(tmp_path, monkeypatch):
    monkeypatch.setattr(testgen.llm, "complete", lambda dev, user, **kw: MODEL_OUTPUT)
    res = independent_check(_pr(tmp_path))
    assert res.error == ""
    assert res.dropped_invariants == ["test_invariant_wrong_on_base"]  # bad test, failed on base
    by_id = {e.id: e.severity for e in res.evidence}
    assert by_id["gate::test_invariant_never_negative"] == "block"  # regression
    assert "gate::test_invariant_wrong_on_base" not in by_id
    assert "gate::test_invariant_basic" not in by_id
    assert by_id.get("gate::test_issue_new_rounding") == "review"  # spec may be misread


def test_llm_outage_is_reported_not_silent(tmp_path, monkeypatch):
    def boom(*a, **k):
        raise testgen.llm.LLMError("down")

    monkeypatch.setattr(testgen.llm, "complete", boom)
    res = independent_check(_pr(tmp_path))
    assert "unavailable" in res.error and res.evidence == []
