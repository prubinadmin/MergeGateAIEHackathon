/**
 * @license
 * SPDX-License-Identifier: Apache-2.0
 * 
 * Starter Code Templates for Merge Gate Reviewer
 * Ready-to-run Python and TypeScript implementations + GitHub Action workflow.
 */

export const PYTHON_STARTER_CODE = `#!/usr/bin/env python3
"""
Merge Gate Reviewer - CLI & GitHub Action Starter Code
Built by Michael, TAAZ and Peter at AIE Code Summit 2026 Hackathon (Shack15 SF)

Usage:
    python merge_gate.py --pr 412 --diff pr_412.diff --issue "Issue #1892: Tiered billing discounts"
"""

import sys
import json
import re
import math
import hashlib
import argparse
from datetime import datetime
from typing import List, Dict, Any, Tuple

RECENCY_LAMBDA = 0.1155  # ~6 month half-life

ANTI_GAMING_RULES = [
    {
        "id": "AG-01",
        "name": "DELETED_TEST",
        "severity": "critical",
        "pattern": r"^-(def test_|test\\(|it\\(|describe\\()",
        "desc": "Deleted existing test case in test file"
    },
    {
        "id": "AG-02",
        "name": "SKIPPED_OR_DISABLED_TEST",
        "severity": "critical",
        "pattern": r"^\\+(it\\.skip|test\\.skip|@pytest\\.mark\\.skip|@unittest\\.skip|xit\\()",
        "desc": "Skipped or disabled tests in diff"
    },
    {
        "id": "AG-03",
        "name": "WEAKENED_ASSERT",
        "severity": "high",
        "pattern": r"^\\+(expect\\(.*\\)\\.toBeTruthy\\(\\)|expect\\(.*\\)\\.toBeDefined\\(\\)|assert\\s+True)",
        "desc": "Weakened assertion from strict equality to loose truthiness"
    },
    {
        "id": "AG-04",
        "name": "MOCKED_CODE_UNDER_TEST",
        "severity": "critical",
        "pattern": r"^\\+(jest\\.spyOn|vi\\.spyOn|patch\\.object|sinon\\.stub)",
        "desc": "Mocked target unit under test in test suite"
    }
]

def parse_diff_owners(diff_text: str) -> List[Dict[str, Any]]:
    """
    Parses git blame / diff hunks and calculates line ownership
    weighted by recency decay: Score = lines * exp(-lambda * delta_months)
    """
    # Demo mock attributing lines for Peter, TAAZ, Michael based on changed files
    now = datetime(2026, 11, 7)
    if "pricing" in diff_text or "billing" in diff_text:
        last_touched = "2026-03-14"
        delta_months = (now - datetime(2026, 3, 14)).days / 30.4375
        lines = 42
        score = lines * math.exp(-RECENCY_LAMBDA * delta_months)
        return [{"name": "Peter", "lines": lines, "last_touched": last_touched, "score": round(score, 2)}]
    elif "auth" in diff_text or "session" in diff_text:
        last_touched = "2026-09-02"
        delta_months = (now - datetime(2026, 9, 2)).days / 30.4375
        lines = 22
        score = lines * math.exp(-RECENCY_LAMBDA * delta_months)
        return [{"name": "TAAZ", "lines": lines, "last_touched": last_touched, "score": round(score, 2)}]
    else:
        last_touched = "2026-10-14"
        delta_months = (now - datetime(2026, 10, 14)).days / 30.4375
        lines = 16
        score = lines * math.exp(-RECENCY_LAMBDA * delta_months)
        return [{"name": "Michael", "lines": lines, "last_touched": last_touched, "score": round(score, 2)}]

def check_anti_gaming(diff_text: str) -> List[Dict[str, Any]]:
    """Deterministic anti-gaming checks on raw diff text"""
    violations = []
    lines = diff_text.splitlines()
    for idx, line in enumerate(lines, 1):
        for rule in ANTI_GAMING_RULES:
            if re.search(rule["pattern"], line):
                violations.append({
                    "type": "rule",
                    "id": rule["id"],
                    "detail": f"{rule['name']}: {rule['desc']} at line {idx}",
                    "severity": rule["severity"]
                })
    return violations

def run_independent_sandbox(pr_id: str, issue_text: str) -> Tuple[List[Dict[str, Any]], bool]:
    """
    Executes independent test derived strictly from issue text and public interface.
    Never sees PR author's reasoning or test mocks.
    """
    evidence = []
    passed = True
    
    # In production, this compiles the test container and runs pytest / vitest in isolation
    if "412" in pr_id or "pricing" in issue_text.lower():
        # Peter's pricing test case failure
        evidence.append({
            "type": "failing_test",
            "id": "IT-102",
            "detail": "test_enterprise_threshold_boundary failed: Expected volume discount 750000, got 0."
        })
        passed = False
    elif "418" in pr_id or "session" in issue_text.lower():
        evidence.append({
            "type": "failing_test",
            "id": "IT-201",
            "detail": "test_session_expiry_rejection failed: Expired session accepted due to loose boolean assert."
        })
        passed = False
        
    return evidence, passed

def main():
    parser = argparse.ArgumentParser(description="Merge Gate Reviewer CLI")
    parser.add_argument("--pr", required=True, help="PR identifier e.g. PR-412")
    parser.add_argument("--diff", help="Path to diff file, or stdin", default=None)
    parser.add_argument("--issue", required=True, help="Issue specification description")
    args = parser.parse_args()

    diff_text = open(args.diff).read() if args.diff else sys.stdin.read()

    # 1. Line Owners
    owners = parse_diff_owners(diff_text)
    primary_owner = owners[0]["name"] if owners else "Engineers"

    # 2. Anti-Gaming Checks
    rule_evidence = check_anti_gaming(diff_text)

    # 3. Independent Tests Sandbox
    test_evidence, tests_passed = run_independent_sandbox(args.pr, args.issue)

    all_evidence = rule_evidence + test_evidence

    # 4. Deterministic Verdict (No LLM makes the verdict!)
    has_critical_rule = any(e.get("severity") == "critical" for e in rule_evidence)
    if not tests_passed or has_critical_rule:
        verdict = "BLOCK"
    elif len(rule_evidence) > 0:
        verdict = "REVIEW"
    else:
        verdict = "PASS"

    # 5. Plain English 2-3 Line Summary for iMessage
    if verdict == "BLOCK":
        top_reason = all_evidence[0]["id"] if allEvidence else "fault detected"
        summary = f"PR #{args.pr} broke independent tests on your code (rule/test {top_reason}). Reply BLOCK to stop, or WHY for traceback."
    else:
        summary = f"PR #{args.pr} cleanly passed independent tests on your code. No anti-gaming violations."

    # 6. Run Hash for Replayability
    run_hash = hashlib.sha256(f"{args.pr}:{verdict}:{len(all_evidence)}".encode()).hexdigest()[:32]

    # 7. Exact JSON Contract Fixed for Owners
    result = {
        "pr_id": args.pr,
        "verdict": verdict,
        "evidence": all_evidence,
        "owners": owners,
        "summary": summary,
        "run_hash": run_hash
    }

    print(json.dumps(result, indent=2))

if __name__ == "__main__":
    main()
`;

export const TYPESCRIPT_STARTER_CODE = `/**
 * Merge Gate Reviewer - TypeScript / Node.js Engine
 * Fixed Interface Contract Implementation
 */

import { createHash } from 'crypto';

export interface CodeOwner {
  name: string;
  lines: number;
  last_touched: string;
}

export interface EvidenceItem {
  type: 'failing_test' | 'rule';
  id: string;
  detail: string;
}

export interface MergeGateResult {
  pr_id: string;
  verdict: 'BLOCK' | 'REVIEW' | 'PASS';
  evidence: EvidenceItem[];
  owners: CodeOwner[];
  summary: string;
  run_hash: string;
}

export async function runMergeGate(
  prId: string,
  diffText: string,
  issueDescription: string
): Promise<MergeGateResult> {
  const evidence: EvidenceItem[] = [];

  // Deterministic Anti-Gaming Rules
  if (/^-(test\\(|it\\(|def test_)/m.test(diffText)) {
    evidence.push({
      type: 'rule',
      id: 'AG-01',
      detail: 'Deleted existing test case in test file'
    });
  }

  if (/^\\+(it\\.skip|test\\.skip|@pytest\\.mark\\.skip)/m.test(diffText)) {
    evidence.push({
      type: 'rule',
      id: 'AG-02',
      detail: 'Skipped or disabled tests in diff'
    });
  }

  if (/^\\+.*(\\.toBeTruthy\\(\\)|\\.toBeDefined\\(\\)|assert\\s+True)/m.test(diffText)) {
    evidence.push({
      type: 'rule',
      id: 'AG-03',
      detail: 'Weakened assertion: strict match replaced with truthiness'
    });
  }

  // Recency-decay line owner calculation
  const owners: CodeOwner[] = [
    { name: 'Peter', lines: 42, last_touched: '2026-03-14' }
  ];

  // Deterministic Verdict Logic
  const hasBlocker = evidence.some(e => e.id === 'AG-01' || e.id === 'AG-02' || e.type === 'failing_test');
  const verdict = hasBlocker ? 'BLOCK' : evidence.length > 0 ? 'REVIEW' : 'PASS';

  const summary = verdict === 'BLOCK'
    ? \`PR #\${prId} failed Merge Gate on your code. Reply BLOCK to stop, or WHY for traceback.\`
    : \`PR #\${prId} clean. Independent tests passed.\`;

  const run_hash = createHash('sha256')
    .update(\`\${prId}:\${verdict}:\${summary}\`)
    .digest('hex')
    .slice(0, 32);

  return {
    pr_id: prId,
    verdict,
    evidence,
    owners,
    summary,
    run_hash
  };
}
`;

export const GITHUB_ACTION_WORKFLOW = `name: "Merge Gate Safety Reviewer"

on:
  pull_request:
    types: [opened, synchronize, reopened]

jobs:
  merge-gate:
    name: "Merge Gate Review"
    runs-on: ubuntu-latest
    steps:
      - name: Checkout Code
        uses: actions/checkout@v4
        with:
          fetch-depth: 0 # Full history needed for git blame -L and recency weighting

      - name: Setup Python
        uses: actions/setup-python@v5
        with:
          python-version: '3.11'

      - name: Generate Diff & Run Merge Gate
        id: gate
        # untrusted PR fields go through env, never inline \${{ }} in run: (prevents shell injection)
        env:
          PR_BODY: \${{ github.event.pull_request.body }}
          BASE_REF: \${{ github.base_ref }}
          PR_NUMBER: \${{ github.event.pull_request.number }}
        run: |
          git diff "origin/\$BASE_REF...HEAD" > pr.diff
          python scripts/merge_gate.py \\
            --pr "PR-\$PR_NUMBER" \\
            --diff pr.diff \\
            --issue "\$PR_BODY" > gate_result.json
          cat gate_result.json
          
          VERDICT=$(jq -r '.verdict' gate_result.json)
          echo "verdict=$VERDICT" >> $GITHUB_OUTPUT
          if [ "$VERDICT" = "BLOCK" ]; then
            echo "Merge Gate returned BLOCK. Notifying owner via iMessage."
            exit 1
          fi

      - name: Dispatch iMessage to Line Owner
        if: always()
        env:
          MERGE_GATE_SMS_KEY: \${{ secrets.MERGE_GATE_SMS_KEY }}
        run: |
          # Sends instant iMessage alert to original author
          python scripts/notify_owner.py gate_result.json
`;
