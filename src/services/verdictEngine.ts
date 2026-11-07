/**
 * @license
 * SPDX-License-Identifier: Apache-2.0
 * 
 * Deterministic Verdict Engine & iMessage Formatter
 * Pure deterministic logic (no LLM decision) that generates the fixed
 * MergeGateResult JSON contract.
 */

import {
  AntiGamingViolation,
  CodeOwner,
  EvidenceItem,
  IndependentTestCase,
  MergeGateResult,
  PullRequest,
  Verdict
} from '../types/mergeGate';
import { computeRunHash } from './independentRunner';

export async function evaluateMergeGate(
  pr: PullRequest,
  owners: CodeOwner[],
  antiGamingViolations: AntiGamingViolation[],
  independentTests: IndependentTestCase[]
): Promise<MergeGateResult> {
  const primaryOwner = owners[0] || { name: 'Engineering Team', lines: 0, last_touched: '2026-01-01' };
  const evidence: EvidenceItem[] = [];

  // 1. Gather Anti-Gaming Rule Evidence
  for (const v of antiGamingViolations) {
    evidence.push({
      type: 'rule',
      id: v.ruleId,
      rule_name: v.ruleName,
      detail: `${v.ruleName}: ${v.description} in ${v.file}:${v.line}`,
      severity: v.severity,
      code_snippet: v.snippet,
      file: v.file,
      line_number: v.line
    });
  }

  // 2. Gather Failing Independent Test Evidence
  const failingTests = independentTests.filter(t => !t.passed);
  for (const t of failingTests) {
    evidence.push({
      type: 'failing_test',
      id: t.id,
      detail: `${t.name} failed: ${t.requirement}. ${t.errorTrace || ''}`,
      expected: t.expected,
      actual: t.actual,
      severity: 'critical'
    });
  }

  // 3. Deterministic Verdict Rules (No LLM makes the verdict)
  let verdict: Verdict = 'PASS';

  const hasFailingTests = failingTests.length > 0;
  const hasCriticalAntiGaming = antiGamingViolations.some(v => v.severity === 'critical');
  const hasHighAntiGaming = antiGamingViolations.some(v => v.severity === 'high');

  if (hasFailingTests || hasCriticalAntiGaming) {
    verdict = 'BLOCK';
  } else if (hasHighAntiGaming || antiGamingViolations.length > 0) {
    verdict = 'REVIEW';
  } else {
    verdict = 'PASS';
  }

  // 4. Generate 2-3 Line Plain-English Summary for the owner's iMessage
  let summary = '';
  if (verdict === 'BLOCK') {
    if (hasFailingTests && hasCriticalAntiGaming) {
      const topRule = antiGamingViolations[0];
      const topTest = failingTests[0];
      summary = `PR #${pr.number} by ${pr.author} violates rule ${topRule.ruleId} (${topRule.ruleName}) and broke independent test ${topTest.id} on your code. Reply BLOCK to stop, or WHY for traceback.`;
    } else if (hasFailingTests) {
      const topTest = failingTests[0];
      summary = `PR #${pr.number} by ${pr.author} broke your ${topTest.targetFunction}. The PR's own tests passed, but independent test ${topTest.id} failed. Reply BLOCK to stop, or WHY for traceback.`;
    } else {
      const topRule = antiGamingViolations[0];
      summary = `PR #${pr.number} by ${pr.author} triggered anti-gaming rule ${topRule.ruleId} (${topRule.ruleName}) in your module. Reply BLOCK to stop, or WHY for traceback.`;
    }
  } else if (verdict === 'REVIEW') {
    summary = `PR #${pr.number} by ${pr.author} touches ${primaryOwner.lines} lines of your code with potential assert softening (${antiGamingViolations[0]?.ruleId}). Independent tests passed. Reply WHY to inspect.`;
  } else {
    summary = `PR #${pr.number} by ${pr.author} cleanly touches ${primaryOwner.lines} lines you wrote. All independent tests passed with zero anti-gaming violations. Passing merge gate.`;
  }

  // 5. Generate Replayable Run Hash
  const hashPayload = JSON.stringify({
    pr_id: pr.id,
    verdict,
    violations: antiGamingViolations.map(v => v.ruleId),
    failing_test_ids: failingTests.map(t => t.id),
    primary_owner: primaryOwner.name,
    timestamp: '2026-11-07T12:00:00Z'
  });
  const run_hash = await computeRunHash(hashPayload);

  return {
    pr_id: pr.id,
    verdict,
    evidence,
    owners: owners.map(o => ({
      name: o.name,
      lines: o.lines,
      last_touched: o.last_touched
    })),
    summary,
    run_hash
  };
}
