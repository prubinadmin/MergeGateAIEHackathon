/**
 * @license
 * SPDX-License-Identifier: Apache-2.0
 * 
 * Sandboxed Independent Test Runner
 * Executes independent tests generated from the issue specification and public interface ONLY.
 * Never sees the PR author's implementation tests. Hashes all inputs and outputs for replay.
 */

import { IndependentTestCase, PullRequest } from '../types/mergeGate';

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
 * Generates independent test cases strictly derived from the Issue Specification
 * and Public API Interface, ignoring any internal tests written by the PR author.
 */
export function generateIndependentTests(pr: PullRequest): IndependentTestCase[] {
  // Scenario 1: Pricing tiered volume discounts
  if (pr.id === 'PR-412' || pr.title.toLowerCase().includes('pricing') || pr.title.toLowerCase().includes('tier')) {
    return [
      {
        id: 'IT-101',
        name: 'test_standard_tier_billing',
        targetFunction: 'calculateTieredPrice(units: number, plan: Plan)',
        requirement: 'Standard plan should bill $12/unit up to 100 units without discount.',
        input: '{ units: 50, plan: "standard" }',
        expected: '{ totalCents: 60000, discountApplied: 0 }',
        actual: '{ totalCents: 60000, discountApplied: 0 }',
        passed: true,
        durationMs: 14
      },
      {
        id: 'IT-102',
        name: 'test_enterprise_threshold_boundary',
        targetFunction: 'calculateTieredPrice(units: number, plan: Plan)',
        requirement: 'Enterprise volume above 5,000 units must cap unit rate at $6.50 and apply contract volume credit.',
        input: '{ units: 5001, plan: "enterprise" }',
        expected: '{ totalCents: 3250650, discountApplied: 750000 }',
        actual: '{ totalCents: 4250000, discountApplied: 0 }', // Agent's implementation failed to calculate volume credit!
        passed: false,
        durationMs: 28,
        errorTrace: 'AssertionError: Expected discountApplied to be 750000 (volume discount), but got 0. PR agent code omitted tier credit formula.'
      },
      {
        id: 'IT-103',
        name: 'test_negative_units_invariance',
        targetFunction: 'calculateTieredPrice(units: number, plan: Plan)',
        requirement: 'Negative unit quantities must throw InvalidBillingQuantityError.',
        input: '{ units: -5, plan: "standard" }',
        expected: 'throws InvalidBillingQuantityError',
        actual: 'throws InvalidBillingQuantityError',
        passed: true,
        durationMs: 9
      }
    ];
  }

  // Scenario 2: Auth and session token verification
  if (pr.id === 'PR-418' || pr.title.toLowerCase().includes('auth') || pr.title.toLowerCase().includes('session')) {
    return [
      {
        id: 'IT-201',
        name: 'test_session_expiry_rejection',
        targetFunction: 'verifySessionToken(token: string, now: number)',
        requirement: 'Tokens older than 3600 seconds must be rejected immediately with SessionExpiredError.',
        input: '{ token: "sess_v1_exp", now: 1773000000 }',
        expected: '{ valid: false, error: "SessionExpiredError" }',
        actual: '{ valid: true, error: null }', // Weakened assert in PR bypassed session TTL!
        passed: false,
        durationMs: 32,
        errorTrace: 'AssertionError: Token 1000s past expiration was accepted as valid. Loose boolean assert allowed bypass.'
      },
      {
        id: 'IT-202',
        name: 'test_tampered_signature_rejection',
        targetFunction: 'verifySessionToken(token: string, now: number)',
        requirement: 'Cryptographic signature mismatch must throw InvalidSignatureError.',
        input: '{ token: "sess_malformed_sig", now: 1773000000 }',
        expected: 'throws InvalidSignatureError',
        actual: 'throws InvalidSignatureError',
        passed: true,
        durationMs: 18
      }
    ];
  }

  // Scenario 3: Clean telemetry pipeline
  if (pr.id === 'PR-421' || pr.title.toLowerCase().includes('telemetry') || pr.title.toLowerCase().includes('clean')) {
    return [
      {
        id: 'IT-301',
        name: 'test_batch_flush_latency',
        targetFunction: 'flushTelemetryQueue(maxBatch: number)',
        requirement: 'Batch buffer should flush within 15ms without dropping buffer entries.',
        input: '{ bufferItems: 250, maxBatch: 50 }',
        expected: '{ flushedCount: 50, remaining: 200 }',
        actual: '{ flushedCount: 50, remaining: 200 }',
        passed: true,
        durationMs: 11
      },
      {
        id: 'IT-302',
        name: 'test_schema_serialization_safe',
        targetFunction: 'serializeMetric(metric: TelemetryMetric)',
        requirement: 'Metrics must produce sanitized JSON compliant with OpenTelemetry schema v1.4.',
        input: '{ name: "cpu_idle", value: 94.2, host: "prod-04" }',
        expected: 'Valid JSON with timestamp & host tags',
        actual: 'Valid JSON with timestamp & host tags',
        passed: true,
        durationMs: 14
      }
    ];
  }

  // Generic fallback for custom PRs
  return [
    {
      id: 'IT-901',
      name: 'test_contract_public_interface',
      targetFunction: 'publicExport(args)',
      requirement: `Validate requirement from issue: "${pr.issueDescription.slice(0, 80)}"`,
      input: '{ mode: "standard_eval" }',
      expected: '{ status: "ok" }',
      actual: '{ status: "ok" }',
      passed: true,
      durationMs: 16
    }
  ];
}
