"""Ownership resolver (owner: Michael): who wrote the lines this PR changes.

git blame on the base ref for every changed/removed line, weighted by lines and recency.
CODEOWNERS is only the fallback.
"""

from __future__ import annotations

from .pr import PullRequest
from .schema import Owner


def resolve_owners(pr: PullRequest) -> list[Owner]:
    """Owners sorted by score, highest first. owners[0] gets the iMessage."""
    raise NotImplementedError
