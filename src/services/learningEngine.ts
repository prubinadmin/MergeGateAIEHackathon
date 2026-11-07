/**
 * @license
 * SPDX-License-Identifier: Apache-2.0
 * 
 * Secondary Learning Track & Gate Rule Evolution (Gate vN+1)
 * Evaluates owner feedback ("FALSE ALARM"), benchmarks rule changes on held-out PRs,
 * and auto-adopts or rolls back versions based on catch rate vs false block rate.
 */

import { GateRuleVersion } from '../types/mergeGate';

export const INITIAL_GATE_VERSIONS: GateRuleVersion[] = [
  {
    version: 'Gate v1.0',
    releasedAt: '2026-09-15',
    catchRate: 91.2,
    falseBlockRate: 4.8,
    status: 'deprecated',
    rulesCount: 4,
    heldOutTestCount: 150,
    changeNote: 'Initial baseline with basic test deletion & skip detection.'
  },
  {
    version: 'Gate v1.1',
    releasedAt: '2026-10-10',
    catchRate: 94.6,
    falseBlockRate: 2.3,
    status: 'deprecated',
    rulesCount: 5,
    heldOutTestCount: 200,
    changeNote: 'Added AG-04 target module mock detection. Reduced false blocks by ignoring test mock setup in integration fixtures.'
  },
  {
    version: 'Gate v1.2',
    releasedAt: '2026-11-01',
    catchRate: 97.4,
    falseBlockRate: 0.9,
    status: 'active',
    rulesCount: 6,
    heldOutTestCount: 280,
    changeNote: 'Added recency-decay line blame weighting and AG-03 weakened assert AST heuristics.',
    ownerFeedbackTrigger: 'Feedback from Peter Chen on pricing boundary assertions.'
  }
];

export interface BenchmarkEvaluationResult {
  proposedVersion: string;
  catchRate: number;
  falseBlockRate: number;
  previousCatchRate: number;
  previousFalseBlockRate: number;
  adopted: boolean;
  decisionReason: string;
  heldOutEvaluated: number;
}

export function evaluateFeedbackAndEvolveGate(
  feedbackPrId: string,
  ruleId: string,
  ownerName: string,
  currentVersions: GateRuleVersion[]
): { updatedVersions: GateRuleVersion[]; result: BenchmarkEvaluationResult } {
  const activeVersion = currentVersions.find(v => v.status === 'active') || currentVersions[currentVersions.length - 1];
  const versionNum = parseFloat(activeVersion.version.replace('Gate v', ''));
  const nextVersionStr = `Gate v${(versionNum + 0.1).toFixed(1)}`;

  // Simulate evaluation on 300 held-out historical PRs
  const heldOutCount = 310;
  
  // Example scenario: tuning AG-03 or AG-05 to reduce false positive
  // Catch rate stays high (97.8%), false block rate drops from 0.9% to 0.5%
  const newCatchRate = 97.8;
  const newFalseBlockRate = 0.5;

  const catchRateDelta = newCatchRate - activeVersion.catchRate;
  const falseBlockDelta = newFalseBlockRate - activeVersion.falseBlockRate;

  // Adoption criteria: Catch rate must rise (or hold) AND false blocks must not rise
  const willAdopt = catchRateDelta >= -0.1 && falseBlockDelta <= 0;

  const decisionReason = willAdopt
    ? `Adopted: Catch rate +${catchRateDelta.toFixed(1)}% (${newCatchRate}%) with false blocks reduced by ${Math.abs(falseBlockDelta).toFixed(1)}% (${newFalseBlockRate}%). Evaluated on ${heldOutCount} held-out PRs.`
    : `Rolled back: Proposed rule relaxed defect detection, increasing false passes. Reverting to ${activeVersion.version}.`;

  const newVersionEntry: GateRuleVersion = {
    version: nextVersionStr,
    releasedAt: new Date().toISOString().split('T')[0],
    catchRate: newCatchRate,
    falseBlockRate: newFalseBlockRate,
    status: willAdopt ? 'active' : 'rolled_back',
    rulesCount: activeVersion.rulesCount,
    heldOutTestCount: heldOutCount,
    changeNote: `Tuned rule ${ruleId} based on FALSE ALARM feedback from ${ownerName} on ${feedbackPrId}.`,
    ownerFeedbackTrigger: `${ownerName} flagged ${ruleId} on ${feedbackPrId}`
  };

  const updatedVersions = currentVersions.map(v => 
    willAdopt && v.status === 'active' ? { ...v, status: 'deprecated' as const } : v
  );
  updatedVersions.push(newVersionEntry);

  return {
    updatedVersions,
    result: {
      proposedVersion: nextVersionStr,
      catchRate: newCatchRate,
      falseBlockRate: newFalseBlockRate,
      previousCatchRate: activeVersion.catchRate,
      previousFalseBlockRate: activeVersion.falseBlockRate,
      adopted: willAdopt,
      decisionReason,
      heldOutEvaluated: heldOutCount
    }
  };
}
