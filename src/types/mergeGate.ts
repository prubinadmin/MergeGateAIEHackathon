/**
 * @license
 * SPDX-License-Identifier: Apache-2.0
 * 
 * Merge Gate Core Types
 * Built for AIE Code Summit 2026 Hackathon (Shack15 SF)
 * Exact interface contract fixed for owners.
 */

export type Verdict = 'BLOCK' | 'REVIEW' | 'PASS';

export type EvidenceType = 'failing_test' | 'rule';

export interface EvidenceItem {
  type: EvidenceType;
  id: string; // e.g. "IT-102" or "AG-01"
  detail: string;
  rule_name?: string;
  severity?: 'critical' | 'high' | 'medium' | 'info';
  code_snippet?: string;
  expected?: string;
  actual?: string;
  file?: string;
  line_number?: number;
}

export interface CodeOwner {
  name: string;
  lines: number;
  last_touched: string; // e.g. "2026-03-14"
  handle?: string;
  phone?: string;
  role?: string;
  score?: number; // recency decay * line count
  blame_details?: Array<{
    line_range: string;
    commit: string;
    date: string;
  }>;
}

/**
 * The fixed contract interface between owners and Merge Gate.
 */
export interface MergeGateResult {
  pr_id: string;
  verdict: Verdict;
  evidence: EvidenceItem[];
  owners: CodeOwner[];
  summary: string;
  run_hash: string;
}

export interface DiffHunk {
  oldStart: number;
  oldLines: number;
  newStart: number;
  newLines: number;
  lines: string[];
}

export interface DiffFile {
  filename: string;
  status: 'modified' | 'added' | 'deleted';
  oldPath?: string;
  newPath?: string;
  blameAuthor: string;
  blameDate: string;
  blameCommit: string;
  hunks: DiffHunk[];
  rawContentBefore?: string;
  rawContentAfter?: string;
}

export interface PullRequest {
  id: string;
  number: number;
  title: string;
  branch: string;
  author: string;
  authorType: 'agent' | 'external' | 'internal';
  repo: string;
  issueDescription: string;
  publicInterface: string;
  createdAt: string;
  diffSummary: string;
  files: DiffFile[];
  prTestStatus: 'passed' | 'failed' | 'none';
  status: 'OPEN' | 'BLOCKED' | 'APPROVED' | 'IN_REVIEW';
  statusReason?: string;
}

export interface IndependentTestCase {
  id: string;
  name: string;
  targetFunction: string;
  requirement: string;
  input: string;
  expected: string;
  actual?: string;
  passed: boolean;
  durationMs: number;
  errorTrace?: string;
}

export interface AntiGamingViolation {
  ruleId: string;
  ruleName: string;
  severity: 'critical' | 'high' | 'medium';
  file: string;
  line: number;
  description: string;
  snippet: string;
}

export interface PhoneMessage {
  id: string;
  prId: string;
  recipientName: string;
  recipientPhone: string;
  sender: 'merge-gate' | 'owner';
  body: string;
  timestamp: string;
  actionTaken?: 'BLOCK' | 'WHY' | 'OK' | 'FALSE_ALARM';
  evidenceLink?: string;
}

export interface GateRuleVersion {
  version: string;
  releasedAt: string;
  catchRate: number; // percentage, e.g. 96.4
  falseBlockRate: number; // percentage, e.g. 1.2
  status: 'active' | 'evaluating' | 'rolled_back' | 'deprecated';
  rulesCount: number;
  heldOutTestCount: number;
  changeNote: string;
  ownerFeedbackTrigger?: string;
}
