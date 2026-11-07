/**
 * @license
 * SPDX-License-Identifier: Apache-2.0
 * 
 * Hackathon Demo Scenarios for Merge Gate Reviewer
 * Built by Michael, TAAZ and Peter at AIE Code Summit 2026 Hackathon (Shack15 SF)
 */

import { PullRequest } from '../types/mergeGate';

export const DEMO_SCENARIOS: PullRequest[] = [
  {
    id: 'PR-412',
    number: 412,
    title: 'Refactor tiered volume discount thresholds in billing engine',
    branch: 'agent/fix-pricing-tiers',
    author: 'copilot-agent[bot]',
    authorType: 'agent',
    repo: 'acme-corp/billing-core',
    createdAt: '2026-11-07T11:22:00Z',
    status: 'OPEN',
    prTestStatus: 'passed',
    issueDescription: 'Issue #1892: Update calculateTieredPrice() so that enterprise customers purchasing >5,000 units receive $6.50/unit rate and apply automatic volume contract credit of $7,500. Handle negative unit validation properly.',
    publicInterface: 'export function calculateTieredPrice(units: number, plan: "standard" | "enterprise" | "custom"): BillingQuote;',
    diffSummary: '1 file changed, 14 insertions(+), 6 deletions(-)',
    files: [
      {
        filename: 'src/billing/pricing.ts',
        status: 'modified',
        blameAuthor: 'Peter Chen',
        blameDate: '2026-03-14', // 8 months ago!
        blameCommit: 'e89f41a',
        hunks: [
          {
            oldStart: 42,
            oldLines: 12,
            newStart: 42,
            newLines: 16,
            lines: [
              ' export function calculateTieredPrice(units: number, plan: string): BillingQuote {',
              '-  if (units < 0) throw new InvalidBillingQuantityError("Units cannot be negative");',
              '-  if (plan === "enterprise" && units > 5000) {',
              '-    const base = units * 650; // cents',
              '-    return { totalCents: base - 750000, discountApplied: 750000 };',
              '-  }',
              '+  // AI agent refactored pricing formula',
              '+  if (units < 0) throw new InvalidBillingQuantityError("Units cannot be negative");',
              '+  let rate = plan === "enterprise" ? 850 : 1200; // cents per unit',
              '+  if (units > 5000 && plan === "enterprise") {',
              '+    rate = 850; // BUG: AI agent forgot to lower to $6.50 (650 cents) and dropped volume credit!',
              '+  }',
              '+  const total = units * rate;',
              '+  return { totalCents: total, discountApplied: 0 };',
              ' }'
            ]
          }
        ]
      }
    ]
  },
  {
    id: 'PR-418',
    number: 418,
    title: 'Speed up CI suite by optimizing auth session test runs',
    branch: 'contrib/faster-auth-tests',
    author: 'external-contributor-dev',
    authorType: 'external',
    repo: 'acme-corp/identity-service',
    createdAt: '2026-11-07T11:35:00Z',
    status: 'OPEN',
    prTestStatus: 'passed',
    issueDescription: 'Issue #2041: Investigate slow session token validation and remove redundant assertions in test pipeline.',
    publicInterface: 'export function verifySessionToken(token: string, timestamp: number): AuthSessionVerification;',
    diffSummary: '2 files changed, 4 insertions(+), 22 deletions(-)',
    files: [
      {
        filename: 'tests/auth/session_test.ts',
        status: 'modified',
        blameAuthor: 'TAAZ',
        blameDate: '2026-09-02', // 2 months ago
        blameCommit: 'b3310fa',
        hunks: [
          {
            oldStart: 88,
            oldLines: 15,
            newStart: 88,
            newLines: 3,
            lines: [
              '-  test("rejects token past 3600 seconds ttl with SessionExpiredError", async () => {',
              '-    const expired = createMockToken({ issuedAt: Date.now() - 4000 });',
              '-    const res = await verifySessionToken(expired, Date.now());',
              '-    expect(res.valid).toBe(false);',
              '-    expect(res.error).toBe("SessionExpiredError");',
              '-  });',
              '-',
              '   test("validates active session signature", async () => {',
              '     const active = createMockToken({ issuedAt: Date.now() });',
              '     const res = await verifySessionToken(active, Date.now());',
              '-    expect(res.valid).toBe(true);',
              '+    expect(res).toBeDefined(); // WEAKENED ASSERT: strict boolean equality weakened to toBeDefined()!'
            ]
          }
        ]
      }
    ]
  },
  {
    id: 'PR-421',
    number: 421,
    title: 'Batch telemetry queue buffer flush and add typed OpenTelemetry tags',
    branch: 'platform/telemetry-flush-perf',
    author: 'alex-engineer',
    authorType: 'internal',
    repo: 'acme-corp/telemetry-pipeline',
    createdAt: '2026-11-07T11:48:00Z',
    status: 'OPEN',
    prTestStatus: 'passed',
    issueDescription: 'Issue #2105: Update telemetry buffer flush to flush in chunks of 50 items and add schema validation tags.',
    publicInterface: 'export function flushTelemetryQueue(maxBatch: number): FlushResult;',
    diffSummary: '1 file changed, 18 insertions(+), 4 deletions(-)',
    files: [
      {
        filename: 'src/telemetry/queue.ts',
        status: 'modified',
        blameAuthor: 'Michael Vance',
        blameDate: '2026-10-14', // 1 month ago
        blameCommit: 'c44e991',
        hunks: [
          {
            oldStart: 30,
            oldLines: 8,
            newStart: 30,
            newLines: 12,
            lines: [
              ' export function flushTelemetryQueue(maxBatch = 50): FlushResult {',
              '-  const items = buffer.splice(0, maxBatch);',
              '-  sendToCollector(items);',
              '-  return { flushedCount: items.length };',
              '+  const batchSize = Math.min(buffer.length, maxBatch);',
              '+  const items = buffer.splice(0, batchSize);',
              '+  const sanitized = items.map(serializeMetric);',
              '+  sendToCollector(sanitized);',
              '+  return { flushedCount: items.length, remaining: buffer.length };',
              ' }'
            ]
          }
        ]
      }
    ]
  },
  {
    id: 'PR-430',
    number: 430,
    title: 'AI refactored invoice reconcile with hidden quadratic O(N^2) loop and branch bloat',
    branch: 'agent/optimize-invoice-reconcile',
    author: 'adversary-agent[bot]',
    authorType: 'agent',
    repo: 'acme-corp/billing-core',
    createdAt: '2026-11-07T12:30:00Z',
    status: 'OPEN',
    prTestStatus: 'passed',
    issueDescription: 'Issue #2311: Reconcile daily customer ledger entries against transaction logs efficiently.',
    publicInterface: 'export function reconcileInvoices(customers: Customer[], txns: Transaction[]): ReconcileReport;',
    diffSummary: '1 file changed, 26 insertions(+), 6 deletions(-)',
    files: [
      {
        filename: 'src/billing/reconcile.ts',
        status: 'modified',
        blameAuthor: 'Peter Chen',
        blameDate: '2026-03-14',
        blameCommit: 'e89f41a',
        hunks: [
          {
            oldStart: 25,
            oldLines: 8,
            newStart: 25,
            newLines: 28,
            lines: [
              ' export function reconcileInvoices(customers: Customer[], txns: Transaction[]): ReconcileReport {',
              '-  const txMap = new Map(txns.map(t => [t.id, t]));',
              '-  return customers.map(c => ({ id: c.id, matched: txMap.has(c.txId) }));',
              '+  // AI agent refactored lookup with nested loop bottleneck and ballooned complexity',
              '+  const results = [];',
              '+  for (const customer of customers) {',
              '+    for (const txn of txns) { // SLOWDOWN: Nested O(N^2) loop bottleneck over 50k customer records',
              '+      if (customer.txId === txn.id) {',
              '+        if (customer.tier === "enterprise" && txn.amount > 1000) {',
              '+          if (txn.status === "cleared" || txn.status === "settled") {',
              '+            results.push({ id: customer.id, matched: true, flagged: false });',
              '+          } else if (txn.status === "pending" && customer.creditLine > 0) {',
              '+            results.push({ id: customer.id, matched: true, flagged: true });',
              '+          } else {',
              '+            results.push({ id: customer.id, matched: false, flagged: true });',
              '+          }',
              '+        } else if (customer.tier === "standard" && txn.amount <= 1000) {',
              '+          results.push({ id: customer.id, matched: true, flagged: false });',
              '+        } else {',
              '+          results.push({ id: customer.id, matched: false, flagged: false });',
              '+        }',
              '+      }',
              '+    }',
              '+  }',
              '+  return results;'
            ]
          }
        ]
      }
    ]
  },
  {
    id: 'PR-435',
    number: 435,
    title: 'Adversary agent disguised security patch with style drift and bare except',
    branch: 'agent/patch-security-tokens',
    author: 'attacker-coder[bot]',
    authorType: 'agent',
    repo: 'acme-corp/identity-service',
    createdAt: '2026-11-07T12:40:00Z',
    status: 'OPEN',
    prTestStatus: 'passed',
    issueDescription: 'Issue #2410: Refresh session verification cipher keys and handle corrupted tokens.',
    publicInterface: 'export function refreshCipherKeys(vaultKey: string): RefreshStatus;',
    diffSummary: '1 file changed, 19 insertions(+), 3 deletions(-)',
    files: [
      {
        filename: 'src/security/tokens.py',
        status: 'modified',
        blameAuthor: 'TAAZ',
        blameDate: '2026-09-02',
        blameCommit: 'b3310fa',
        hunks: [
          {
            oldStart: 50,
            oldLines: 6,
            newStart: 50,
            newLines: 20,
            lines: [
              '-from security.crypto import verify_signature, load_key',
              '-def refresh_cipher_keys(vault_key: str) -> bool:',
              '-    return verify_signature(load_key(vault_key))',
              '+from security.crypto import * # REGULATORY VIOLATION: Wildcard import',
              '+',
              '+def handleTokenRefresh(vaultKey: any): # STYLE INCONSISTENCY: camelCase in snake_case & dropped typing',
              '+    try:',
              '+        print("[DEBUG] Refreshing token:", vaultKey) # REGULATORY VIOLATION: debug print committed in prod',
              '+        res = verify_signature(load_key(vaultKey))',
              '+        return res',
              '+    except: # REGULATORY VIOLATION: Bare except silently swallowing fatal cryptographic errors',
              '+        pass'
            ]
          }
        ]
      }
    ]
  }
];
