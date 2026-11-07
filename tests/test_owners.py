import os

from merge_gate.owners import resolve_owners
from merge_gate.pr import PullRequest

from helpers import git, write

PETER = ("Peter", "peter@example.com")
TAAZ = ("TAAZ", "taaz@example.com")
MICHAEL = ("Michael", "michael@example.com")


def _repo(tmp_path):
    repo = str(tmp_path / "repo")
    os.makedirs(repo)
    git(repo, "init", "-q", "-b", "main")
    git(repo, "config", "user.email", "x@example.com")
    git(repo, "config", "user.name", "X")
    return repo


def _commit(repo, files, who, msg="c"):
    write(repo, files)
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", msg, author=who)


PRICING = "def apply_discount(price, pct):\n    return max(0.0, price * (1 - pct / 100))\n"
CART = "def total(xs):\n    s = 0\n    for x in xs:\n        s += x\n    return s\n"


def test_routes_to_the_author_of_the_changed_lines(tmp_path):
    repo = _repo(tmp_path)
    _commit(repo, {"shop/pricing.py": PRICING}, PETER)
    _commit(repo, {"shop/cart.py": CART}, TAAZ)
    _commit(repo, {"README.md": "hi\n"}, MICHAEL)
    git(repo, "checkout", "-q", "-b", "pr/1")
    _commit(repo, {"shop/pricing.py": PRICING.replace("max(0.0, ", "(")}, ("Agent", "agent@bots.dev"))
    pr = PullRequest("p", repo, "main", "pr/1")
    owners = resolve_owners(pr)
    assert owners[0].email == "peter@example.com"
    assert all(o.email != "taaz@example.com" for o in owners)


def test_insertion_is_charged_to_the_enclosing_function(tmp_path):
    repo = _repo(tmp_path)
    _commit(repo, {"shop/cart.py": CART}, TAAZ)
    _commit(repo, {"shop/cart.py": CART + "\n\ndef empty():\n    return []\n"}, MICHAEL)
    git(repo, "checkout", "-q", "-b", "pr/1")
    _commit(repo, {"shop/cart.py": (CART.replace("        s += x\n", "        s += x\n        s -= 0\n")) + "\n\ndef empty():\n    return []\n"}, ("Agent", "a@b.dev"))
    owners = resolve_owners(PullRequest("p", repo, "main", "pr/1"))
    assert owners[0].email == "taaz@example.com"


def test_codeowners_fallback_for_new_files(tmp_path):
    repo = _repo(tmp_path)
    _commit(repo, {"CODEOWNERS": "shop/ @payments-team\n", "shop/__init__.py": ""}, MICHAEL)
    git(repo, "checkout", "-q", "-b", "pr/1")
    _commit(repo, {"shop/new.py": "X = 1\n"}, ("Agent", "a@b.dev"))
    owners = resolve_owners(PullRequest("p", repo, "main", "pr/1"))
    assert [o.name for o in owners] == ["payments-team"]
