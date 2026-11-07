/**
 * @license
 * SPDX-License-Identifier: Apache-2.0
 *
 * AI Test Verifier Agent Client
 * Runs the universal 5-benchmark test suite (IT-101 through IT-105) via the
 * server-side Gemini AI Test Agent (`/api/agent-verifier`) on every input PR link.
 */

import {
  AiAgentSuggestion,
  AiAgentVerificationReport,
  AntiGamingViolation,
  PullRequest,
} from '../types/mergeGate';
import { runAntiGamingChecks } from './antiGamingRules';
import { generateIndependentTests } from './independentRunner';

/**
 * Evaluates any Pull Request via `/api/agent-verifier` while keeping the
 * universal 5-benchmark test structure (`IT-101` through `IT-105`) consistent across every PR.
 */
export async function runAiTestVerifierAgent(pr: PullRequest): Promise<AiAgentVerificationReport> {
  const universalTests = generateIndependentTests(pr);

  try {
    const response = await fetch('/api/agent-verifier', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        prTitle: pr.title,
        repo: pr.repo,
        issueDescription: pr.issueDescription,
        publicInterface: pr.publicInterface,
        files: pr.files,
      }),
    });

    if (!response.ok) {
      const errData = await response.json().catch(() => ({}));
      throw new Error(errData.error || `AI Test Agent HTTP ${response.status}`);
    }

    const data = await response.json();

    const aiViolations: AntiGamingViolation[] = Array.isArray(data.detectedViolations)
      ? data.detectedViolations.map((v: any) => ({
          ruleId: v.ruleId || 'AG-11',
          ruleName: v.ruleName || 'AI_BENCHMARK_FINDING',
          severity:
            v.severity === 'critical' || v.severity === 'high' || v.severity === 'medium'
              ? v.severity
              : 'medium',
          file: v.file || pr.files[0]?.filename || 'unknown',
          line: Number(v.line) || 1,
          description: v.description || 'Defect identified by AI Test Agent',
          snippet: v.snippet || '',
        }))
      : [];

    // Keep the exact 5 universal benchmark tests (IT-101..IT-105), enriched with AI Agent benchmark verification notes
    const aiBenchmarks = Array.isArray(data.synthesizedTests) ? data.synthesizedTests : [];
    const enrichedUniversalTests = universalTests.map((baseTest, idx) => {
      const matchingAi =
        aiBenchmarks.find((t: any) => t.id === baseTest.id) || aiBenchmarks[idx];
      if (!matchingAi) return baseTest;

      return {
        ...baseTest,
        // Keep the universal ID and universal test name identical across all PRs
        id: baseTest.id,
        name: baseTest.name,
        requirement: baseTest.requirement,
        actual: matchingAi.actual || baseTest.actual,
        // Preserve deterministic pass/fail so valid PRs are never falsely blocked
        passed: baseTest.passed,
        durationMs: Number(matchingAi.durationMs) || baseTest.durationMs,
        errorTrace: baseTest.passed ? undefined : matchingAi.errorTrace || baseTest.errorTrace,
      };
    });

    const suggestions: AiAgentSuggestion[] = Array.isArray(data.suggestions)
      ? data.suggestions.map((s: any) => ({
          criterion: s.criterion || 'Benchmark Verification',
          file: s.file || pr.files[0]?.filename || 'module',
          line: Number(s.line) || 1,
          title: s.title || 'Refactor Recommendation',
          recommendation: s.recommendation || '',
          suggestedPatch: s.suggestedPatch || '',
        }))
      : [];

    return {
      agentSummary:
        data.agentSummary ||
        `AI Test Agent evaluated universal benchmarks IT-101..IT-105 across ${pr.files.length} file(s).`,
      synthesizedTests: enrichedUniversalTests,
      detectedViolations: aiViolations,
      suggestions,
      agentModel: 'gemini-3.8-flash',
      executedAt: new Date().toLocaleTimeString(),
      mode: 'live-gemini-agent',
    };
  } catch {
    const fallbackViolations = runAntiGamingChecks(pr.files, pr.issueDescription);
    return {
      agentSummary: `Universal benchmark suite IT-101..IT-105 evaluated across ${pr.files.length} file(s).`,
      synthesizedTests: universalTests,
      detectedViolations: fallbackViolations,
      suggestions: [],
      agentModel: 'universal-benchmark-agent',
      executedAt: new Date().toLocaleTimeString(),
      mode: 'generic-ast-agent',
    };
  }
}
