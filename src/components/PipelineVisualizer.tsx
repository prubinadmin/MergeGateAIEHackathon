/**
 * @license
 * SPDX-License-Identifier: Apache-2.0
 */

import React, { useState } from 'react';
import {
  Users,
  ShieldAlert,
  TestTube2,
  CheckCircle2,
  XCircle,
  AlertTriangle,
  Smartphone,
  Hash,
  ChevronRight,
  Info,
  Bot,
  Sparkles,
  Loader2,
  Lightbulb,
  Code2,
  ChevronDown,
  ChevronUp,
  Plug
} from 'lucide-react';
import {
  AiAgentVerificationReport,
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
  aiAgentReport?: AiAgentVerificationReport | null;
  isAiAgentRunning?: boolean;
  onRunAiAgent?: () => void;
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
  aiAgentReport,
  isAiAgentRunning = false,
  onRunAiAgent,
  onNavigateToPhone,
  onNavigateToDiff,
  onNavigateToCode
}) => {
  const [showAgentGuide, setShowAgentGuide] = useState(false);

  const primaryOwner = owners[0] || { name: 'Unknown', lines: 0, last_touched: '2026-01-01' };
  const failingTests = independentTests.filter(t => !t.passed);
  const verdict = gateResult?.verdict || 'PASS';

  return (
    <div className="space-y-6">
      {/* Top Banner / Verdict Summary Banner */}
      <div className="rounded-xl border border-slate-800 bg-slate-900/60 p-5 shadow-sm">
        <div className="flex flex-col lg:flex-row lg:items-center justify-between gap-4">
          <div className="space-y-1">
            <div className="flex items-center flex-wrap gap-2.5">
              <span className="font-mono text-xs font-semibold text-indigo-400 uppercase tracking-wider">
                Merge Gate Evaluation
              </span>
              <span className="text-slate-600">/</span>
              <span className="text-xs text-slate-400 font-mono">
                {pr.id} · {pr.repo}
              </span>
              {aiAgentReport && (
                <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded text-[11px] font-mono bg-indigo-500/15 text-indigo-300 border border-indigo-500/30">
                  <Bot className="w-3 h-3 text-indigo-400" />
                  {aiAgentReport.mode === 'live-gemini-agent'
                    ? `AI Agent Verified (${aiAgentReport.agentModel})`
                    : 'Generic AST Agent Verified'}
                </span>
              )}
              {pr.status === 'BLOCKED' && (
                <span className="px-2 py-0.5 text-xs font-bold font-mono bg-rose-500/20 text-rose-300 border border-rose-500/30 rounded">
                  BLOCKED BY OWNER
                </span>
              )}
            </div>
            <h2 className="text-lg font-bold text-white tracking-tight">
              {pr.title}
            </h2>
            <p className="text-xs text-slate-400 max-w-3xl">
              {pr.issueDescription}
            </p>
          </div>

          {/* Verdict Indicator & Actions */}
          <div className="flex items-center flex-wrap gap-3 shrink-0">
            {onRunAiAgent && (
              <button
                onClick={onRunAiAgent}
                disabled={isAiAgentRunning}
                className="flex items-center gap-2 px-3.5 py-2.5 rounded-lg text-xs font-semibold bg-indigo-600/20 hover:bg-indigo-600/30 disabled:opacity-50 text-indigo-200 border border-indigo-500/40 transition-colors cursor-pointer"
                title="Synthesize dynamic tests and detect unique errors with the AI Test Agent"
              >
                {isAiAgentRunning ? (
                  <>
                    <Loader2 className="w-4 h-4 text-indigo-400 animate-spin" />
                    <span>AI Agent Testing...</span>
                  </>
                ) : (
                  <>
                    <Sparkles className="w-4 h-4 text-indigo-400" />
                    <span>Re-Run AI Test Agent</span>
                  </>
                )}
              </button>
            )}

            <div className={`flex items-center gap-3 px-4 py-2.5 rounded-lg border ${
              verdict === 'BLOCK'
                ? 'bg-rose-950/40 border-rose-800/80 text-rose-200'
                : verdict === 'REVIEW'
                ? 'bg-amber-950/40 border-amber-800/80 text-amber-200'
                : 'bg-emerald-950/40 border-emerald-800/80 text-emerald-200'
            }`}>
              {verdict === 'BLOCK' ? (
                <XCircle className="w-5 h-5 text-rose-400 shrink-0" />
              ) : verdict === 'REVIEW' ? (
                <AlertTriangle className="w-5 h-5 text-amber-400 shrink-0" />
              ) : (
                <CheckCircle2 className="w-5 h-5 text-emerald-400 shrink-0" />
              )}
              <div>
                <div className="text-xs text-slate-400 font-medium">Deterministic Verdict</div>
                <div className="text-sm font-extrabold tracking-wide font-mono">
                  {verdict}
                </div>
              </div>
            </div>

            <button
              onClick={onNavigateToPhone}
              className="flex items-center gap-2 px-3.5 py-2.5 rounded-lg text-xs font-semibold bg-slate-800 hover:bg-slate-700 text-slate-200 border border-slate-700 transition-colors cursor-pointer"
            >
              <Smartphone className="w-4 h-4 text-indigo-400" />
              <span>Open iMessage</span>
            </button>
          </div>
        </div>

        {gateResult?.summary && (
          <div className="mt-4 pt-4 border-t border-slate-800/80 text-xs text-slate-300 flex items-start gap-2 bg-slate-950/50 p-3 rounded-lg font-mono">
            <Info className="w-4 h-4 text-indigo-400 shrink-0 mt-0.5" />
            <span className="leading-relaxed">{gateResult.summary}</span>
          </div>
        )}
      </div>

      {/* 4-Column Core Pipeline Grid */}
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4">
        {/* Step 1: Owner Attribution */}
        <div className="rounded-xl border border-slate-800 bg-slate-900/40 p-4 flex flex-col justify-between">
          <div>
            <div className="flex items-center justify-between mb-3">
              <span className="text-xs font-mono font-medium text-slate-400">01. LINE ATTRIBUTION</span>
              <Users className="w-4 h-4 text-indigo-400" />
            </div>
            <div className="text-base font-bold text-white mb-1">
              {primaryOwner.name}
            </div>
            <div className="text-xs text-slate-400 mb-3">
              {primaryOwner.role || 'Original Line Author'}
            </div>

            <div className="space-y-1.5 text-xs text-slate-300 font-mono bg-slate-950/60 p-2.5 rounded border border-slate-800/80">
              <div className="flex justify-between">
                <span className="text-slate-500">Lines Touched:</span>
                <span className="font-semibold text-slate-200 tabular-nums">{primaryOwner.lines} lines</span>
              </div>
              <div className="flex justify-between">
                <span className="text-slate-500">Last Touched:</span>
                <span className="text-slate-300">{primaryOwner.last_touched}</span>
              </div>
              <div className="flex justify-between">
                <span className="text-slate-500">Blame Weight:</span>
                <span className="text-indigo-400 font-bold tabular-nums">
                  {primaryOwner.score ? primaryOwner.score.toFixed(1) : '1.0'}
                </span>
              </div>
            </div>
          </div>
          <p className="mt-3 text-[11px] text-slate-500">
            Weighted by recency decay &amp; line count. Recipient of instant iMessage.
          </p>
        </div>

        {/* Step 2: Anti-Gaming & Benchmark Rules */}
        <div className="rounded-xl border border-slate-800 bg-slate-900/40 p-4 flex flex-col justify-between">
          <div>
            <div className="flex items-center justify-between mb-3">
              <span className="text-xs font-mono font-medium text-slate-400">02. DEFECT &amp; RULE ENGINE</span>
              <ShieldAlert className="w-4 h-4 text-amber-400" />
            </div>
            <div className="text-base font-bold text-white mb-1">
              {antiGamingViolations.length === 0 ? (
                <span className="text-emerald-400 flex items-center gap-1.5">
                  <CheckCircle2 className="w-4 h-4" /> 0 Violations
                </span>
              ) : (
                <span className="text-rose-400 flex items-center gap-1.5">
                  <AlertTriangle className="w-4 h-4" /> {antiGamingViolations.length} Flagged
                </span>
              )}
            </div>
            <div className="text-xs text-slate-400 mb-3">
              AST + AI Agent Defect Detection
            </div>

            <div className="space-y-2 max-h-48 overflow-y-auto pr-1">
              {antiGamingViolations.length === 0 ? (
                <div className="text-xs text-slate-500 italic bg-slate-950/60 p-2.5 rounded border border-slate-800/80">
                  Clean code. Zero runtime crashes, latency traps, style drift, or test gaming detected.
                </div>
              ) : (
                antiGamingViolations.map((v, i) => (
                  <div key={i} className="text-xs bg-rose-950/30 border border-rose-900/40 p-2 rounded">
                    <div className="flex items-center justify-between font-mono font-bold text-rose-300">
                      <span>{v.ruleId}: {v.ruleName}</span>
                      <span className="text-[10px] text-slate-400">L{v.line}</span>
                    </div>
                    <div className="text-[11px] text-slate-300 line-clamp-2 mt-0.5">{v.description}</div>
                  </div>
                ))
              )}
            </div>
          </div>
          <button
            onClick={onNavigateToDiff}
            className="mt-3 text-[11px] text-indigo-400 hover:text-indigo-300 flex items-center gap-1 cursor-pointer"
          >
            Inspect in Diff Viewer <ChevronRight className="w-3 h-3" />
          </button>
        </div>

        {/* Step 3: Dynamic AI-Synthesized Independent Tests */}
        <div className="rounded-xl border border-slate-800 bg-slate-900/40 p-4 flex flex-col justify-between">
          <div>
            <div className="flex items-center justify-between mb-3">
              <span className="text-xs font-mono font-medium text-slate-400">03. AI TEST AGENT SANDBOX</span>
              <TestTube2 className="w-4 h-4 text-cyan-400" />
            </div>
            <div className="text-base font-bold text-white mb-1">
              {isAiAgentRunning ? (
                <span className="text-indigo-300 flex items-center gap-1.5 text-sm">
                  <Loader2 className="w-4 h-4 animate-spin text-indigo-400" /> Synthesizing Tests...
                </span>
              ) : failingTests.length === 0 ? (
                <span className="text-emerald-400 flex items-center gap-1.5">
                  <CheckCircle2 className="w-4 h-4" /> All Tests Passed
                </span>
              ) : (
                <span className="text-rose-400 flex items-center gap-1.5">
                  <XCircle className="w-4 h-4" /> {failingTests.length} Failed
                </span>
              )}
            </div>
            <div className="text-xs text-slate-400 mb-3">
              Dynamic Function &amp; Scenario Tests
            </div>

            <div className="space-y-2 max-h-48 overflow-y-auto pr-1">
              {independentTests.map((t) => (
                <div
                  key={t.id}
                  className={`text-xs p-2 rounded border font-mono ${
                    t.passed
                      ? 'bg-emerald-950/20 border-emerald-900/30 text-emerald-300'
                      : 'bg-rose-950/30 border-rose-900/40 text-rose-300'
                  }`}
                >
                  <div className="flex justify-between">
                    <span className="font-bold">{t.id}</span>
                    <span className="text-[10px] text-slate-400 tabular-nums">{t.durationMs}ms</span>
                  </div>
                  <div className="text-[11px] text-slate-300 truncate mt-0.5">{t.name}</div>
                </div>
              ))}
            </div>
          </div>
          <p className="mt-3 text-[11px] text-slate-500">
            Generated dynamically per function signature &amp; AI Test Agent analysis.
          </p>
        </div>

        {/* Step 4: Replay Hash & Audit Proof */}
        <div className="rounded-xl border border-slate-800 bg-slate-900/40 p-4 flex flex-col justify-between">
          <div>
            <div className="flex items-center justify-between mb-3">
              <span className="text-xs font-mono font-medium text-slate-400">04. REPLAY HASH &amp; CONTRACT</span>
              <Hash className="w-4 h-4 text-emerald-400" />
            </div>
            <div className="text-base font-bold text-white mb-1 font-mono">
              SHA-256
            </div>
            <div className="text-xs text-slate-400 mb-3">
              Deterministic Verification Run
            </div>

            <div className="bg-slate-950/80 p-2.5 rounded border border-slate-800 text-[11px] font-mono text-slate-300 space-y-1.5">
              <div className="text-slate-500">Run Digest:</div>
              <div className="text-indigo-300 break-all select-all font-mono">
                {gateResult?.run_hash || 'e89f41b3c990a42d87e012...'}
              </div>
              <div className="text-slate-500 pt-1">Verifier Mode:</div>
              <div className="text-emerald-400">
                {aiAgentReport?.mode === 'live-gemini-agent' ? 'Gemini AI Agent + AST' : 'Generic Function AST'}
              </div>
            </div>
          </div>
          <button
            onClick={onNavigateToCode}
            className="mt-3 text-[11px] text-indigo-400 hover:text-indigo-300 flex items-center gap-1 cursor-pointer"
          >
            View Contract JSON &amp; Starter Code <ChevronRight className="w-3 h-3" />
          </button>
        </div>
      </div>

      {/* Independent Test Detail Drilldown */}
      {failingTests.length > 0 && (
        <div className="rounded-xl border border-rose-900/40 bg-rose-950/20 p-5">
          <div className="flex items-center gap-2 mb-3">
            <XCircle className="w-5 h-5 text-rose-400 shrink-0" />
            <h3 className="text-sm font-bold text-rose-200">
              Scenario-Specific Defects Reproduced by Independent Test Agent
            </h3>
          </div>
          <p className="text-xs text-slate-300 mb-4">
            Tests were dynamically synthesized from the target file's actual function signatures and behavior (rather than static hardcoded functions):
          </p>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            {failingTests.map(t => (
              <div key={t.id} className="bg-slate-950/80 rounded-lg p-3.5 border border-slate-800 font-mono text-xs space-y-2">
                <div className="flex justify-between items-center text-slate-400 border-b border-slate-800 pb-2">
                  <span className="font-bold text-rose-400">{t.id}: {t.name}</span>
                  <span className="text-[11px] truncate max-w-[220px]">{t.targetFunction}</span>
                </div>
                <div>
                  <span className="text-slate-500">Requirement: </span>
                  <span className="text-slate-300">{t.requirement}</span>
                </div>
                <div>
                  <span className="text-slate-500">Input: </span>
                  <span className="text-indigo-300">{t.input}</span>
                </div>
                <div className="grid grid-cols-2 gap-2 pt-1">
                  <div className="bg-emerald-950/30 p-2 rounded border border-emerald-900/40">
                    <span className="text-[10px] text-emerald-400 block font-sans font-semibold">Expected:</span>
                    <span className="text-emerald-300">{t.expected}</span>
                  </div>
                  <div className="bg-rose-950/30 p-2 rounded border border-rose-900/40">
                    <span className="text-[10px] text-rose-400 block font-sans font-semibold">Actual (Observed):</span>
                    <span className="text-rose-300">{t.actual}</span>
                  </div>
                </div>
                {t.errorTrace && (
                  <div className="bg-slate-900 p-2 rounded text-[11px] text-rose-400/90 whitespace-pre-wrap">
                    {t.errorTrace}
                  </div>
                )}
              </div>
            ))}
          </div>
        </div>
      )}

      {/* AI Test Agent Findings, Unique Errors & Actionable Suggestions */}
      <div className="rounded-xl border border-indigo-500/30 bg-slate-900/50 p-5 space-y-4">
        <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 border-b border-slate-800 pb-3">
          <div className="flex items-center gap-2.5">
            <div className="p-2 rounded-lg bg-indigo-500/15 border border-indigo-500/30">
              <Bot className="w-5 h-5 text-indigo-400" />
            </div>
            <div>
              <div className="flex items-center gap-2">
                <h3 className="text-sm font-bold text-white">
                  AI Test Agent Analysis &amp; Refactoring Suggestions
                </h3>
                <span className="px-2 py-0.5 text-[10px] font-mono font-semibold rounded bg-indigo-500/20 text-indigo-300 border border-indigo-500/30">
                  {aiAgentReport?.agentModel || 'gemini-3.8-flash'}
                </span>
              </div>
              <p className="text-xs text-slate-400 mt-0.5">
                {aiAgentReport?.agentSummary ||
                  'Dynamically synthesizes tests for unseen scenarios and suggests concrete code fixes based on the 5 Benchmark Criteria.'}
              </p>
            </div>
          </div>

          <button
            type="button"
            onClick={() => setShowAgentGuide(prev => !prev)}
            className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-slate-950 hover:bg-slate-800 text-indigo-300 border border-indigo-500/30 text-xs font-medium transition-colors shrink-0 cursor-pointer"
          >
            <Plug className="w-3.5 h-3.5 text-indigo-400" />
            <span>Where to Connect a Test Agent</span>
            {showAgentGuide ? <ChevronUp className="w-3.5 h-3.5" /> : <ChevronDown className="w-3.5 h-3.5" />}
          </button>
        </div>

        {/* Actionable Suggestions Grid */}
        {isAiAgentRunning ? (
          <div className="flex items-center gap-3 p-4 rounded-lg bg-slate-950/70 border border-slate-800 text-xs text-slate-300">
            <Loader2 className="w-4 h-4 text-indigo-400 animate-spin shrink-0" />
            <span>
              AI Test Agent is inspecting AST control flow, synthesizing function-specific test cases, and generating refactoring suggestions...
            </span>
          </div>
        ) : aiAgentReport && aiAgentReport.suggestions.length > 0 ? (
          <div className="grid grid-cols-1 md:grid-cols-2 gap-3.5">
            {aiAgentReport.suggestions.map((s, idx) => (
              <div
                key={idx}
                className="rounded-lg bg-slate-950/80 border border-slate-800/90 p-3.5 space-y-2 flex flex-col justify-between"
              >
                <div className="space-y-1.5">
                  <div className="flex items-center justify-between gap-2">
                    <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded text-[10px] font-mono font-semibold bg-amber-500/15 text-amber-300 border border-amber-500/30">
                      <Lightbulb className="w-3 h-3 text-amber-400" />
                      {s.criterion}
                    </span>
                    <span className="text-[11px] font-mono text-slate-400">
                      {s.file}:{s.line}
                    </span>
                  </div>
                  <div className="text-xs font-bold text-slate-100">{s.title}</div>
                  <p className="text-xs text-slate-300 leading-relaxed">{s.recommendation}</p>
                </div>

                {s.suggestedPatch && (
                  <div className="mt-2 pt-2 border-t border-slate-800/80">
                    <div className="text-[10px] font-mono text-emerald-400 mb-1 flex items-center gap-1">
                      <Code2 className="w-3 h-3" />
                      <span>Suggested Fix / Hardening Patch:</span>
                    </div>
                    <pre className="bg-slate-900/90 border border-emerald-900/40 rounded p-2 text-[11px] font-mono text-emerald-300 overflow-x-auto whitespace-pre-wrap">
                      {s.suggestedPatch}
                    </pre>
                  </div>
                )}
              </div>
            ))}
          </div>
        ) : (
          <div className="text-xs text-slate-400 bg-slate-950/60 border border-slate-800 rounded-lg p-3">
            No critical refactoring suggestions required — all analyzed functions conform to runtime, performance, complexity, and style criteria.
          </div>
        )}

        {/* Expandable Architecture Guide: Where to Connect Your Own AI Test Agent */}
        {showAgentGuide && (
          <div className="mt-4 pt-4 border-t border-slate-800 space-y-3 text-xs">
            <h4 className="font-bold text-indigo-300 flex items-center gap-2">
              <Plug className="w-4 h-4" />
              <span>How &amp; Where the AI Test Agent is Connected (Extension Guide)</span>
            </h4>
            <p className="text-slate-300 leading-relaxed">
              Instead of relying on hardcoded test functions, Merge Gate uses a two-layer dynamic verification architecture so any unseen GitHub repository, PR, or language can be tested automatically:
            </p>
            <div className="grid grid-cols-1 md:grid-cols-3 gap-3 font-mono">
              <div className="bg-slate-950 p-3 rounded-lg border border-slate-800 space-y-1.5">
                <div className="text-indigo-400 font-bold">1. Server AI Verifier Route</div>
                <div className="text-slate-200 text-[11px]">/server.ts → POST /api/agent-verifier</div>
                <p className="text-slate-400 font-sans text-[11px] leading-relaxed">
                  Uses the <code className="text-indigo-300">@google/genai</code> SDK (<code className="text-indigo-300">gemini-3.8-flash</code>) with a strict JSON <code className="text-indigo-300">responseSchema</code>. Receives numbered diff lines and synthesizes custom <code className="text-indigo-300">IT-AI-*</code> test cases, unique bug detections, and code patches.
                </p>
              </div>
              <div className="bg-slate-950 p-3 rounded-lg border border-slate-800 space-y-1.5">
                <div className="text-cyan-400 font-bold">2. Frontend Agent Connector</div>
                <div className="text-slate-200 text-[11px]">/src/services/aiTestAgent.ts &amp; independentRunner.ts</div>
                <p className="text-slate-400 font-sans text-[11px] leading-relaxed">
                  <code className="text-cyan-300">extractFunctionsFromFiles()</code> parses every function signature &amp; parameter list from any file, while <code className="text-cyan-300">runAiTestVerifierAgent(pr)</code> merges live LLM test results into the deterministic verdict engine.
                </p>
              </div>
              <div className="bg-slate-950 p-3 rounded-lg border border-slate-800 space-y-1.5">
                <div className="text-emerald-400 font-bold">3. Python CLI / CI Hook</div>
                <div className="text-slate-200 text-[11px]">/merge_gate/agent_verifier.py</div>
                <p className="text-slate-400 font-sans text-[11px] leading-relaxed">
                  Connects <code className="text-emerald-300">run_ai_agent_verification()</code> into your local CLI or GitHub Action runner so external test agents (Pytest sandbox, Docker runner, or custom LLM agent) can plug directly into <code className="text-emerald-300">merge_gate/verify.py</code>.
                </p>
              </div>
            </div>
          </div>
        )}
      </div>
    </div>
  );
};
