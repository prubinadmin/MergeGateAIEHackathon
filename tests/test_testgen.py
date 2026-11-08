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
    monkeypatch.setattr(testgen, "writers", lambda: ["muse"])
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
    monkeypatch.setattr(testgen, "writers", lambda: ["muse"])
    res = independent_check(_pr(tmp_path))
    assert "unavailable" in res.error and res.evidence == []


GEMINI_OUTPUT = '''```python
from shop.pricing import apply_discount


def test_invariant_full_discount_is_free():
    assert apply_discount(50, 100) == 0


def test_issue_over_discount_floors_at_zero():
    assert apply_discount(10, 150) == 0
```'''


def test_two_writers_tests_both_run_under_names_kept_apart(tmp_path, monkeypatch):
    outputs = {"muse": MODEL_OUTPUT, "gemini": GEMINI_OUTPUT}
    monkeypatch.setattr(testgen.llm, "complete", lambda dev, user, provider="muse", **kw: outputs[provider])
    monkeypatch.setattr(testgen.llm, "model_name", lambda p="muse": {"muse": "muse-wonder-1.0", "gemini": "gemini-4-argon"}[p])
    monkeypatch.setattr(testgen, "writers", lambda: ["muse", "gemini"])
    res = independent_check(_pr(tmp_path))
    assert res.error == "" and res.writers == ["muse-wonder-1.0", "gemini-4-argon"]
    by_id = {e.id: e.severity for e in res.evidence}
    assert by_id["gate::test_invariant_never_negative"] == "block"                  # Muse's names unchanged
    assert by_id["gate::test_issue_gemini_over_discount_floors_at_zero"] == "review"  # Gemini's tagged, still classified
    assert res.dropped_invariants == ["test_invariant_wrong_on_base"]                  # base filtering unchanged


def test_one_writer_down_the_other_still_runs_and_the_gap_is_reported(tmp_path, monkeypatch):
    def complete(dev, user, provider="muse", **kw):
        if provider == "gemini":
            raise testgen.llm.LLMError("quota")
        return MODEL_OUTPUT

    monkeypatch.setattr(testgen.llm, "complete", complete)
    monkeypatch.setattr(testgen.llm, "model_name", lambda p="muse": p)
    monkeypatch.setattr(testgen, "writers", lambda: ["muse", "gemini"])
    res = independent_check(_pr(tmp_path))
    assert res.writers == ["muse"] and "gemini: quota" in res.error
    assert {e.id for e in res.evidence} >= {"gate::test_invariant_never_negative", "gate::test_issue_new_rounding"}
