/**
 * @license
 * SPDX-License-Identifier: Apache-2.0
 */

import React from 'react';
import {
  GitPullRequest,
  Users,
  ShieldAlert,
  TestTube2,
  CheckCircle2,
  XCircle,
  AlertTriangle,
  Smartphone,
  Hash,
  ExternalLink,
  ChevronRight,
  Info
} from 'lucide-react';
import {
  AntiGamingViolation,
  CodeOwner,
  IndependentTestCase,
  MergeGateResult,
  PullRequest
} from '../types/mergeGate';

interface PipelineVisualizerProps {
  pr: PullRequest;
  owners: CodeOwner[];
  antiGamingViolations: AntiGamingViolation[];
  independentTests: IndependentTestCase[];
  gateResult: MergeGateResult | null;
  onNavigateToPhone: () => void;
  onNavigateToDiff: () => void;
  onNavigateToCode: () => void;
}

export const PipelineVisualizer: React.FC<PipelineVisualizerProps> = ({
  pr,
  owners,
  antiGamingViolations,
  independentTests,
  gateResult,
  onNavigateToPhone,
  onNavigateToDiff,
  onNavigateToCode
}) => {
  const primaryOwner = owners[0] || { name: 'Unknown', lines: 0, last_touched: '2026-01-01' };
  const failingTests = independentTests.filter(t => !t.passed);
  const verdict = gateResult?.verdict || 'PASS';

  return (
    <div className="space-y-6">
      {/* Top Banner / Verdict Summary Banner */}
      <div className="rounded-xl border border-yellow-500/25 bg-neutral-950 p-5 shadow-sm">
        <div className="flex flex-col lg:flex-row lg:items-center justify-between gap-4">
          <div className="space-y-1">
            <div className="flex items-center gap-3">
              <span className="font-mono text-xs font-semibold text-yellow-400 uppercase tracking-wider">
                Merge Gate Evaluation
              </span>
              <span className="text-neutral-700">/</span>
              <span className="text-xs text-neutral-400 font-mono">
                {pr.id} · {pr.repo}
              </span>
              {pr.status === 'BLOCKED' && (
                <span className="px-2 py-0.5 text-xs font-bold font-mono bg-rose-500/20 text-rose-300 border border-rose-500/30 rounded">
                  BLOCKED BY OWNER
                </span>
              )}
            </div>
            <h2 className="text-lg font-bold text-white tracking-tight">
              {pr.title}
            </h2>
            <p className="text-xs text-neutral-400 max-w-3xl">
              {pr.issueDescription}
            </p>
          </div>

          {/* Verdict Indicator */}
          <div className="flex items-center gap-4 shrink-0">
            <div className={`flex items-center gap-3 px-4 py-2.5 rounded-lg border ${
              verdict === 'BLOCK'
                ? 'bg-rose-950/40 border-rose-800/80 text-rose-200'
                : verdict === 'REVIEW'
                ? 'bg-yellow-500/15 border-yellow-500/50 text-yellow-200'
                : 'bg-emerald-950/40 border-emerald-800/80 text-emerald-200'
            }`}>
              {verdict === 'BLOCK' ? (
                <XCircle className="w-5 h-5 text-rose-400 shrink-0" />
              ) : verdict === 'REVIEW' ? (
                <AlertTriangle className="w-5 h-5 text-yellow-400 shrink-0" />
              ) : (
                <CheckCircle2 className="w-5 h-5 text-emerald-400 shrink-0" />
              )}
              <div>
                <div className="text-xs text-neutral-400 font-medium">Deterministic Verdict</div>
                <div className="text-sm font-extrabold tracking-wide font-mono">
                  {verdict}
                </div>
              </div>
            </div>

            <button
              onClick={onNavigateToPhone}
              className="flex items-center gap-2 px-3.5 py-2.5 rounded-lg text-xs font-bold bg-yellow-400 hover:bg-yellow-300 text-black border border-yellow-500 transition-colors"
            >
              <Smartphone className="w-4 h-4 text-black" />
              <span>Open iMessage</span>
            </button>
          </div>
        </div>

        {gateResult?.summary && (
          <div className="mt-4 pt-4 border-t border-neutral-800 text-xs text-neutral-200 flex items-start gap-2 bg-black p-3 rounded-lg font-mono border border-yellow-500/20">
            <Info className="w-4 h-4 text-yellow-400 shrink-0 mt-0.5" />
            <span className="leading-relaxed">{gateResult.summary}</span>
          </div>
        )}
      </div>

      {/* 4-Column Core Pipeline Grid */}
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4">
        {/* Step 1: Owner Attribution */}
        <div className="rounded-xl border border-yellow-500/20 bg-neutral-950 p-4 flex flex-col justify-between">
          <div>
            <div className="flex items-center justify-between mb-3">
              <span className="text-xs font-mono font-medium text-yellow-400/90">01. LINE ATTRIBUTION</span>
              <Users className="w-4 h-4 text-yellow-400" />
            </div>
            <div className="text-base font-bold text-white mb-1">
              {primaryOwner.name}
            </div>
            <div className="text-xs text-neutral-400 mb-3">
              {primaryOwner.role || 'Original Line Author'}
            </div>

            <div className="space-y-1.5 text-xs text-neutral-300 font-mono bg-black p-2.5 rounded border border-neutral-800">
              <div className="flex justify-between">
                <span className="text-neutral-500">Lines Touched:</span>
                <span className="font-semibold text-neutral-200 tabular-nums">{primaryOwner.lines} lines</span>
              </div>
              <div className="flex justify-between">
                <span className="text-neutral-500">Last Touched:</span>
                <span className="text-neutral-300">{primaryOwner.last_touched}</span>
              </div>
              <div className="flex justify-between">
                <span className="text-neutral-500">Blame Weight:</span>
                <span className="text-yellow-400 font-bold tabular-nums">
                  {primaryOwner.score ? primaryOwner.score.toFixed(1) : '1.0'}
                </span>
              </div>
            </div>
          </div>
          <p className="mt-3 text-[11px] text-neutral-500">
            Weighted by recency decay & line count. Recipient of instant iMessage.
          </p>
        </div>

        {/* Step 2: Anti-Gaming Rules */}
        <div className="rounded-xl border border-yellow-500/20 bg-neutral-950 p-4 flex flex-col justify-between">
          <div>
            <div className="flex items-center justify-between mb-3">
              <span className="text-xs font-mono font-medium text-yellow-400/90">02. ANTI-GAMING RULES</span>
              <ShieldAlert className="w-4 h-4 text-yellow-400" />
            </div>
            <div className="text-base font-bold text-white mb-1">
              {antiGamingViolations.length === 0 ? (
                <span className="text-emerald-400 flex items-center gap-1.5">
                  <CheckCircle2 className="w-4 h-4" /> 0 Violations
                </span>
              ) : (
                <span className="text-yellow-400 flex items-center gap-1.5">
                  <AlertTriangle className="w-4 h-4" /> {antiGamingViolations.length} Flagged
                </span>
              )}
            </div>
            <div className="text-xs text-neutral-400 mb-3">
              Deterministic AST & Diff Analysis
            </div>

            <div className="space-y-2">
              {antiGamingViolations.length === 0 ? (
                <div className="text-xs text-neutral-500 italic bg-black p-2.5 rounded border border-neutral-800">
                  Clean PR. No deleted tests, weakened assertions, or unit mocks detected.
                </div>
              ) : (
                antiGamingViolations.map((v, i) => (
                  <div key={i} className="text-xs bg-yellow-500/10 border border-yellow-500/30 p-2 rounded">
                    <div className="font-mono font-bold text-yellow-300">{v.ruleId}: {v.ruleName}</div>
                    <div className="text-[11px] text-neutral-300 truncate mt-0.5">{v.description}</div>
                  </div>
                ))
              )}
            </div>
          </div>
          <button
            onClick={onNavigateToDiff}
            className="mt-3 text-[11px] text-yellow-400 hover:text-yellow-300 flex items-center gap-1 font-medium"
          >
            Inspect in Diff Viewer <ChevronRight className="w-3 h-3" />
          </button>
        </div>

        {/* Step 3: Sandboxed Independent Tests */}
        <div className="rounded-xl border border-yellow-500/20 bg-neutral-950 p-4 flex flex-col justify-between">
          <div>
            <div className="flex items-center justify-between mb-3">
              <span className="text-xs font-mono font-medium text-yellow-400/90">03. INDEPENDENT SANDBOX</span>
              <TestTube2 className="w-4 h-4 text-yellow-400" />
            </div>
            <div className="text-base font-bold text-white mb-1">
              {failingTests.length === 0 ? (
                <span className="text-emerald-400 flex items-center gap-1.5">
                  <CheckCircle2 className="w-4 h-4" /> All Tests Passed
                </span>
              ) : (
                <span className="text-rose-400 flex items-center gap-1.5">
                  <XCircle className="w-4 h-4" /> {failingTests.length} Failed
                </span>
              )}
            </div>
            <div className="text-xs text-neutral-400 mb-3">
              Generated from Issue Spec Only
            </div>

            <div className="space-y-2">
              {independentTests.map((t) => (
                <div
                  key={t.id}
                  className={`text-xs p-2 rounded border font-mono ${
                    t.passed
                      ? 'bg-black border-yellow-500/30 text-yellow-300'
                      : 'bg-rose-950/30 border-rose-900/40 text-rose-300'
                  }`}
                >
                  <div className="flex justify-between">
                    <span className="font-bold">{t.id}</span>
                    <span className="text-[10px] text-neutral-400 tabular-nums">{t.durationMs}ms</span>
                  </div>
                  <div className="text-[11px] text-neutral-300 truncate mt-0.5">{t.name}</div>
                </div>
              ))}
            </div>
          </div>
          <p className="mt-3 text-[11px] text-neutral-500">
            Never sees author tests or reasoning. Isolated subprocess.
          </p>
        </div>

        {/* Step 4: Replay Hash & Audit Proof */}
        <div className="rounded-xl border border-yellow-500/20 bg-neutral-950 p-4 flex flex-col justify-between">
          <div>
            <div className="flex items-center justify-between mb-3">
              <span className="text-xs font-mono font-medium text-yellow-400/90">04. REPLAY HASH & CONTRACT</span>
              <Hash className="w-4 h-4 text-yellow-400" />
            </div>
            <div className="text-base font-bold text-white mb-1 font-mono">
              SHA-256
            </div>
            <div className="text-xs text-neutral-400 mb-3">
              Deterministic Verification Run
            </div>

            <div className="bg-black p-2.5 rounded border border-neutral-800 text-[11px] font-mono text-neutral-300 space-y-1.5">
              <div className="text-neutral-500">Run Digest:</div>
              <div className="text-yellow-300 break-all select-all font-mono">
                {gateResult?.run_hash || 'e89f41b3c990a42d87e012...'}
              </div>
              <div className="text-neutral-500 pt-1">Interface:</div>
              <div className="text-yellow-400">Fixed Owner Contract</div>
            </div>
          </div>
          <button
            onClick={onNavigateToCode}
            className="mt-3 text-[11px] text-yellow-400 hover:text-yellow-300 flex items-center gap-1 font-medium"
          >
            View Contract JSON & Starter Code <ChevronRight className="w-3 h-3" />
          </button>
        </div>
      </div>

      {/* Independent Test Detail Drilldown */}
      {failingTests.length > 0 && (
        <div className="rounded-xl border border-rose-900/40 bg-rose-950/20 p-5">
          <div className="flex items-center gap-2 mb-3">
            <XCircle className="w-5 h-5 text-rose-400 shrink-0" />
            <h3 className="text-sm font-bold text-rose-200">
              Reproducing Defect Caught by Independent Test Sandbox
            </h3>
          </div>
          <p className="text-xs text-neutral-300 mb-4">
            The PR author's own tests passed because edge conditions were omitted or assertions loosened.
            Merge Gate's independent test reproduced the defect using the public contract:
          </p>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            {failingTests.map(t => (
              <div key={t.id} className="bg-black rounded-lg p-3.5 border border-neutral-800 font-mono text-xs space-y-2">
                <div className="flex justify-between items-center text-neutral-400 border-b border-neutral-800 pb-2">
                  <span className="font-bold text-rose-400">{t.id}: {t.name}</span>
                  <span className="text-[11px]">{t.targetFunction}</span>
                </div>
                <div>
                  <span className="text-neutral-500">Requirement: </span>
                  <span className="text-neutral-300">{t.requirement}</span>
                </div>
                <div>
                  <span className="text-neutral-500">Input: </span>
                  <span className="text-yellow-300">{t.input}</span>
                </div>
                <div className="grid grid-cols-2 gap-2 pt-1">
                  <div className="bg-emerald-950/30 p-2 rounded border border-emerald-900/40">
                    <span className="text-[10px] text-emerald-400 block font-sans font-semibold">Expected:</span>
                    <span className="text-emerald-300">{t.expected}</span>
                  </div>
                  <div className="bg-rose-950/30 p-2 rounded border border-rose-900/40">
                    <span className="text-[10px] text-rose-400 block font-sans font-semibold">Actual (PR Output):</span>
                    <span className="text-rose-300">{t.actual}</span>
                  </div>
                </div>
                {t.errorTrace && (
                  <div className="bg-neutral-950 p-2 rounded text-[11px] text-rose-400/90 whitespace-pre-wrap">
                    {t.errorTrace}
                  </div>
                )}
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
};
