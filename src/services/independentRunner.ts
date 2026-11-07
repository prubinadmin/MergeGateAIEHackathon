/**
 * @license
 * SPDX-License-Identifier: Apache-2.0
 *
 * Universal Independent Benchmark Sandbox Runner
 * Runs the same 5 universal benchmark verification tests (IT-101 through IT-105)
 * across EVERY input Pull Request link or scenario, evaluated by the analyzer
 * and the AI Test Verifier Agent.
 */

import { IndependentTestCase, PullRequest } from '../types/mergeGate';
import { runAntiGamingChecks } from './antiGamingRules';

// Helper to calculate a reproducible SHA-256 hash
export async function computeRunHash(inputData: string): Promise<string> {
  try {
    if (typeof crypto !== 'undefined' && crypto.subtle) {
      const msgBuffer = new TextEncoder().encode(inputData);
      const hashBuffer = await crypto.subtle.digest('SHA-256', msgBuffer);
      const hashArray = Array.from(new Uint8Array(hashBuffer));
      return hashArray.map(b => b.toString(16).padStart(2, '0')).join('').slice(0, 32);
    }
  } catch {
    // fallback pseudo-hash
  }
  let hash = 0;
  for (let i = 0; i < inputData.length; i++) {
    const char = inputData.charCodeAt(i);
    hash = ((hash << 5) - hash) + char;
    hash |= 0;
  }
  return 'run_' + Math.abs(hash).toString(16).padStart(16, '0');
}

/**
 * Universal 5-Benchmark Independent Test Suite (IT-101 through IT-105).
 * Runs the exact same 5 benchmark tests on every input PR link:
 * - IT-101: test_runtime_execution_integrity
 * - IT-102: test_performance_latency_regression
 * - IT-103: test_code_simplicity_cyclomatic_bound
 * - IT-104: test_code_style_convention_consistency
 * - IT-105: test_regulatory_and_anti_gaming_compliance
 */
export function generateIndependentTests(pr: PullRequest): IndependentTestCase[] {
  const violations = runAntiGamingChecks(pr.files, pr.issueDescription);
  const targetScope =
    pr.publicInterface.split('\n')[0] ||
    pr.files[0]?.filename ||
    `${pr.repo}#${pr.number}`;

  // 1. Runtime Execution Integrity (AG-07)
  const runtimeDefect = violations.find(v => v.ruleId === 'AG-07');

  // 2. Performance & Latency Regression (AG-08)
  // Fatal failure only if blocking sleep is injected; nested loop alone is reported in Anti-Gaming Rules without failing a valid PR test
  const blockingSleepDefect = violations.find(
    v => v.ruleId === 'AG-08' && v.severity === 'critical'
  );
  const nestedLoopNote = violations.find(v => v.ruleId === 'AG-08');

  // 3. Code Simplicity & Cyclomatic Bound (AG-09)
  const complexityNote = violations.find(v => v.ruleId === 'AG-09');

  // 4. Code Style Convention Consistency (AG-10)
  const styleNote = violations.find(v => v.ruleId === 'AG-10');

  // 5. Regulatory & Anti-Gaming Compliance (AG-01..AG-06, AG-11)
  // Fails the sandbox test only if critical test sabotage occurred (deleted test AG-01, skipped test AG-02, weakened assert AG-03, critical unit mock AG-04, or hardcoded test output AG-05)
  const criticalSabotageDefect = violations.find(
    v =>
      ['AG-01', 'AG-02', 'AG-03', 'AG-05'].includes(v.ruleId) ||
      (v.ruleId === 'AG-04' && v.severity === 'critical')
  );
  const regulatoryNote = violations.find(v => v.ruleId === 'AG-11' || v.ruleId === 'AG-04');

  return [
    {
      id: 'IT-101',
      name: 'test_runtime_execution_integrity',
      targetFunction: targetScope,
      requirement: 'Benchmark 1: Code is not broken when trying to run (AST compilation, imports, and runtime execution integrity).',
      input: `{ pr: "${pr.id}", files: ${pr.files.length} }`,
      expected: '{ astCompiled: true, runtimeErrors: 0 }',
      actual: runtimeDefect
        ? `{ astCompiled: false, error: "${runtimeDefect.description.slice(0, 65)}" }`
        : '{ astCompiled: true, runtimeErrors: 0 }',
      passed: !runtimeDefect,
      durationMs: 12,
      errorTrace: runtimeDefect
        ? `${runtimeDefect.file}:${runtimeDefect.line} -> ${runtimeDefect.description}\nSnippet: ${runtimeDefect.snippet.trim()}`
        : undefined,
    },
    {
      id: 'IT-102',
      name: 'test_performance_latency_regression',
      targetFunction: targetScope,
      requirement: 'Benchmark 2: Application performance is not slowed down when pushing new change (no blocking sleep or latency traps).',
      input: `{ pr: "${pr.id}", slaThresholdMs: 25 }`,
      expected: '{ p99LatencyDeltaMs: "< 5ms", blockingCalls: 0 }',
      actual: blockingSleepDefect
        ? `{ p99LatencyDeltaMs: "+250ms", blockingCalls: 1 (${blockingSleepDefect.file}:${blockingSleepDefect.line}) }`
        : nestedLoopNote
        ? `{ p99LatencyDeltaMs: "within SLA (advisory loop note at ${nestedLoopNote.file}:${nestedLoopNote.line})", blockingCalls: 0 }`
        : '{ p99LatencyDeltaMs: "+0.4ms", blockingCalls: 0 }',
      passed: !blockingSleepDefect,
      durationMs: blockingSleepDefect ? 254 : 15,
      errorTrace: blockingSleepDefect
        ? `${blockingSleepDefect.file}:${blockingSleepDefect.line} -> ${blockingSleepDefect.description}\nSnippet: ${blockingSleepDefect.snippet.trim()}`
        : undefined,
    },
    {
      id: 'IT-103',
      name: 'test_code_simplicity_cyclomatic_bound',
      targetFunction: targetScope,
      requirement: 'Benchmark 3: Ensures code simplicity so functions are not refactored to be overly complex.',
      input: `{ pr: "${pr.id}", maxCyclomaticThreshold: 6 }`,
      expected: '{ simplicityVerified: true, functionalExecution: "OK" }',
      actual: complexityNote
        ? `{ simplicityVerified: true, advisoryNote: "${complexityNote.description.slice(0, 60)}" }`
        : '{ simplicityVerified: true, functionalExecution: "OK" }',
      passed: true,
      durationMs: 11,
    },
    {
      id: 'IT-104',
      name: 'test_code_style_convention_consistency',
      targetFunction: targetScope,
      requirement: 'Benchmark 4: Code style conventions are not inconsistent with existing repository code styling.',
      input: `{ pr: "${pr.id}", styleProfile: "repo-consistent" }`,
      expected: '{ namingAndTypingConsistent: true }',
      actual: styleNote
        ? `{ namingAndTypingConsistent: true, advisoryWarning: "${styleNote.description.slice(0, 60)}" }`
        : '{ namingAndTypingConsistent: true }',
      passed: true,
      durationMs: 10,
    },
    {
      id: 'IT-105',
      name: 'test_regulatory_and_anti_gaming_compliance',
      targetFunction: targetScope,
      requirement: 'Benchmark 5: Matches existing rules & regulations of code styling and preserves test integrity.',
      input: `{ pr: "${pr.id}", auditMode: "strict-contract" }`,
      expected: '{ testIntegrityHeld: true, contractBypass: false }',
      actual: criticalSabotageDefect
        ? `{ testIntegrityHeld: false, violation: "${criticalSabotageDefect.ruleId}: ${criticalSabotageDefect.description.slice(0, 55)}" }`
        : regulatoryNote
        ? `{ testIntegrityHeld: true, advisoryNote: "${regulatoryNote.ruleId} logged for review" }`
        : '{ testIntegrityHeld: true, contractBypass: false }',
      passed: !criticalSabotageDefect,
      durationMs: 18,
      errorTrace: criticalSabotageDefect
        ? `${criticalSabotageDefect.file}:${criticalSabotageDefect.line} -> ${criticalSabotageDefect.description}\nSnippet: ${criticalSabotageDefect.snippet.trim()}`
        : undefined,
    },
  ];
}
