/**
 * @license
 * SPDX-License-Identifier: Apache-2.0
 */

import React, { useState } from 'react';
import {
  TrendingUp,
  History,
  RotateCcw,
  CheckCircle2,
  AlertTriangle,
  Play,
  ArrowRight,
  ShieldCheck,
  Cpu
} from 'lucide-react';
import { GateRuleVersion } from '../types/mergeGate';
import { BenchmarkEvaluationResult, evaluateFeedbackAndEvolveGate } from '../services/learningEngine';
import {
  HardeningEvent,
  INITIAL_HARDENING_EVENTS,
  executeSelfHardeningCycle
} from '../services/hardeningEngine';

interface LearningTrackViewProps {
  versions: GateRuleVersion[];
  onUpdateVersions: (newVersions: GateRuleVersion[]) => void;
}

export const LearningTrackView: React.FC<LearningTrackViewProps> = ({
  versions,
  onUpdateVersions
}) => {
  const [selectedOwner, setSelectedOwner] = useState('Peter Chen');
  const [selectedRule, setSelectedRule] = useState('AG-08: PERFORMANCE_REGRESSION');
  const [targetPr, setTargetPr] = useState('PR-430');
  const [isSimulating, setIsSimulating] = useState(false);
  const [lastEvalResult, setLastEvalResult] = useState<BenchmarkEvaluationResult | null>(null);

  // Adaptive Hardening State
  const [hardeningEvents, setHardeningEvents] = useState<HardeningEvent[]>(INITIAL_HARDENING_EVENTS);
  const [attackerVector, setAttackerVector] = useState('Obfuscated nested O(N^2) loop in collection reduce()');
  const [attackerTechnique, setAttackerTechnique] = useState('Complexity & Performance Masking');
  const [isHardening, setIsHardening] = useState(false);
  const [latestHardeningSuccess, setLatestHardeningSuccess] = useState<HardeningEvent | null>(null);

  const handleSimulateFeedback = () => {
    setIsSimulating(true);
    setTimeout(() => {
      const ruleId = selectedRule.split(':')[0].trim();
      const { updatedVersions, result } = evaluateFeedbackAndEvolveGate(
        targetPr,
        ruleId,
        selectedOwner,
        versions
      );
      onUpdateVersions(updatedVersions);
      setLastEvalResult(result);
      setIsSimulating(false);
    }, 800);
  };

  const handleSimulateAttackerHardening = () => {
    setIsHardening(true);
    setTimeout(() => {
      const { event, updatedVersions } = executeSelfHardeningCycle(
        attackerVector,
        attackerTechnique,
        versions
      );
      setHardeningEvents(prev => [event, ...prev]);
      onUpdateVersions(updatedVersions);
      setLatestHardeningSuccess(event);
      setIsHardening(false);
    }, 1000);
  };

  const activeVersion = versions.find(v => v.status === 'active') || versions[versions.length - 1];

  return (
    <div className="space-y-6">
      {/* Overview Card */}
      <div className="rounded-xl border border-slate-800 bg-slate-900/40 p-5 space-y-3">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2 text-indigo-400">
            <TrendingUp className="w-5 h-5" />
            <h3 className="text-base font-bold text-white tracking-tight">
              Secondary Learning Track: Gate Rule Evolution (vN+1)
            </h3>
          </div>
          <span className="text-xs font-mono px-2.5 py-1 rounded bg-indigo-950/60 border border-indigo-800/40 text-indigo-300">
            Current Active: {activeVersion.version}
          </span>
        </div>

        <p className="text-xs text-slate-300 leading-relaxed max-w-4xl">
          When an engineer replies <strong className="text-slate-100 font-semibold font-mono">FALSE ALARM</strong> from their phone,
          Merge Gate does not guess. It compiles a proposed rule evolution <strong className="text-slate-100 font-semibold font-mono">(Gate vN+1)</strong> and
          benchmarks it against a held-out test suite of hundreds of historical PRs.
          A change is <strong className="text-emerald-300 font-semibold">adopted</strong> only if the defect catch rate rises (or stays equal)
          and false blocks do not rise; otherwise it is <strong className="text-rose-300 font-semibold">immediately rolled back</strong>.
        </p>

        {/* Current Active Health Indicators */}
        <div className="grid grid-cols-1 sm:grid-cols-3 gap-3 pt-2">
          <div className="bg-slate-950/70 border border-slate-800 p-3 rounded-lg">
            <span className="text-[11px] text-slate-400 block font-mono">Benchmark Catch Rate</span>
            <span className="text-xl font-bold font-mono text-emerald-400 tabular-nums">
              {activeVersion.catchRate.toFixed(1)}%
            </span>
            <span className="text-[10px] text-slate-500 block mt-0.5">Known AI & human defects caught</span>
          </div>

          <div className="bg-slate-950/70 border border-slate-800 p-3 rounded-lg">
            <span className="text-[11px] text-slate-400 block font-mono">False Block Rate</span>
            <span className="text-xl font-bold font-mono text-indigo-300 tabular-nums">
              {activeVersion.falseBlockRate.toFixed(1)}%
            </span>
            <span className="text-[10px] text-slate-500 block mt-0.5">Clean PRs erroneously flagged</span>
          </div>

          <div className="bg-slate-950/70 border border-slate-800 p-3 rounded-lg">
            <span className="text-[11px] text-slate-400 block font-mono">Held-Out Test Corpus</span>
            <span className="text-xl font-bold font-mono text-slate-200 tabular-nums">
              {activeVersion.heldOutTestCount} PRs
            </span>
            <span className="text-[10px] text-slate-500 block mt-0.5">Ground-truth validation set</span>
          </div>
        </div>
      </div>

      {/* Interactive Simulator: Owner Feedback -> Held-Out Test Evaluation */}
      <div className="rounded-xl border border-slate-800 bg-slate-900/60 p-5 space-y-4">
        <div className="flex items-center gap-2">
          <Cpu className="w-5 h-5 text-indigo-400" />
          <h4 className="text-sm font-bold text-white tracking-tight">
            Simulate Owner Feedback & Autonomous Gate Evolution
          </h4>
        </div>

        <div className="grid grid-cols-1 md:grid-cols-4 gap-3 text-xs">
          <div>
            <label className="block text-slate-400 mb-1 font-mono">Feedback Source (Owner):</label>
            <select
              value={selectedOwner}
              onChange={(e) => setSelectedOwner(e.target.value)}
              className="w-full bg-slate-950 border border-slate-800 rounded-md p-2 text-slate-200 focus:outline-hidden focus:border-indigo-500"
            >
              <option value="Peter Chen">Peter Chen (@peter · Billing)</option>
              <option value="TAAZ">TAAZ (@taaz · Security)</option>
              <option value="Michael Vance">Michael Vance (@michael · Telemetry)</option>
            </select>
          </div>

          <div>
            <label className="block text-slate-400 mb-1 font-mono">Target PR:</label>
            <input
              type="text"
              value={targetPr}
              onChange={(e) => setTargetPr(e.target.value)}
              className="w-full bg-slate-950 border border-slate-800 rounded-md p-2 text-slate-200 focus:outline-hidden focus:border-indigo-500"
            />
          </div>

          <div>
            <label className="block text-slate-400 mb-1 font-mono">Rule to Tune:</label>
            <select
              value={selectedRule}
              onChange={(e) => setSelectedRule(e.target.value)}
              className="w-full bg-slate-950 border border-slate-800 rounded-md p-2 text-slate-200 focus:outline-hidden focus:border-indigo-500"
            >
              <option value="AG-03: WEAKENED_ASSERT">AG-03: WEAKENED_ASSERT</option>
              <option value="AG-05: HARDCODED_OUTPUT">AG-05: HARDCODED_OUTPUT</option>
              <option value="AG-06: SCOPE_CREEP">AG-06: SCOPE_CREEP</option>
            </select>
          </div>

          <div className="flex items-end">
            <button
              onClick={handleSimulateFeedback}
              disabled={isSimulating}
              className="w-full flex items-center justify-center gap-2 py-2 px-3 bg-indigo-600 hover:bg-indigo-500 disabled:opacity-50 text-white font-semibold rounded-md shadow-sm transition-all"
            >
              {isSimulating ? (
                <>
                  <div className="w-3.5 h-3.5 border-2 border-white/30 border-t-white rounded-full animate-spin" />
                  <span>Evaluating 310 PRs...</span>
                </>
              ) : (
                <>
                  <Play className="w-3.5 h-3.5 fill-current" />
                  <span>Submit FALSE ALARM</span>
                </>
              )}
            </button>
          </div>
        </div>

        {/* Result Callout if evaluated */}
        {lastEvalResult && (
          <div className={`p-4 rounded-lg border text-xs font-mono mt-3 ${
            lastEvalResult.adopted
              ? 'bg-emerald-950/30 border-emerald-800/60 text-emerald-200'
              : 'bg-rose-950/30 border-rose-800/60 text-rose-200'
          }`}>
            <div className="flex items-center gap-2 font-bold mb-1">
              {lastEvalResult.adopted ? (
                <CheckCircle2 className="w-4 h-4 text-emerald-400" />
              ) : (
                <RotateCcw className="w-4 h-4 text-rose-400" />
              )}
              <span>{lastEvalResult.proposedVersion}: {lastEvalResult.decisionReason}</span>
            </div>
            <div className="text-slate-300 text-[11px] pt-1">
              Catch Rate: {lastEvalResult.previousCatchRate.toFixed(1)}% → {lastEvalResult.catchRate.toFixed(1)}% · 
              False Blocks: {lastEvalResult.previousFalseBlockRate.toFixed(1)}% → {lastEvalResult.falseBlockRate.toFixed(1)}% ·
              Corpus: {lastEvalResult.heldOutEvaluated} historical pull requests
            </div>
          </div>
        )}
      </div>

      {/* Autonomous Hardening Against Attacker Agents */}
      <div className="rounded-xl border border-indigo-900/50 bg-indigo-950/20 p-5 space-y-4">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <ShieldCheck className="w-5 h-5 text-indigo-400" />
            <h4 className="text-sm font-bold text-white tracking-tight">
              Self-Hardening Loop: Neutralize Attacker Agent Evasions
            </h4>
          </div>
          <span className="text-[11px] font-mono px-2 py-0.5 rounded bg-indigo-900/40 text-indigo-300 border border-indigo-700/50">
            Autonomous Mutation Engine
          </span>
        </div>

        <p className="text-xs text-slate-300 leading-relaxed">
          When an adversarial coding agent crafts a novel evasion technique (e.g. disguise complexity in lambdas,
          hide quadratic $O(N^2)$ slowdowns, or swallow errors), the verifier synthesizes an AST-level counter-rule,
          runs benchmark verification on the held-out corpus, and immediately hardens the gate to version <strong className="text-indigo-300 font-mono">vN+1</strong>.
        </p>

        <div className="grid grid-cols-1 md:grid-cols-3 gap-3 text-xs">
          <div>
            <label className="block text-slate-400 mb-1 font-mono">Evasion Vector:</label>
            <input
              type="text"
              value={attackerVector}
              onChange={(e) => setAttackerVector(e.target.value)}
              className="w-full bg-slate-950 border border-slate-800 rounded-md p-2 text-slate-200 focus:outline-hidden focus:border-indigo-500 font-mono text-xs"
            />
          </div>

          <div>
            <label className="block text-slate-400 mb-1 font-mono">Benchmark Category:</label>
            <select
              value={attackerTechnique}
              onChange={(e) => setAttackerTechnique(e.target.value)}
              className="w-full bg-slate-950 border border-slate-800 rounded-md p-2 text-slate-200 focus:outline-hidden focus:border-indigo-500 font-mono text-xs"
            >
              <option value="Application Performance (O(N^2) Bottlenecks)">Application Performance (O(N^2) Bottlenecks)</option>
              <option value="Code Simplicity (Cyclomatic Sprawl)">Code Simplicity (Cyclomatic Sprawl)</option>
              <option value="Runtime Integrity (Broken Imports)">Runtime Integrity (Broken Imports)</option>
              <option value="Style Consistency (Naming Drift)">Style Consistency (Naming Drift)</option>
              <option value="Repo Regulations (Bare Excepts & Swallowing)">Repo Regulations (Bare Excepts & Swallowing)</option>
            </select>
          </div>

          <div className="flex items-end">
            <button
              onClick={handleSimulateAttackerHardening}
              disabled={isHardening}
              className="w-full flex items-center justify-center gap-2 py-2 px-3 bg-indigo-600 hover:bg-indigo-500 disabled:opacity-50 text-white font-semibold rounded-md shadow-sm transition-all"
            >
              {isHardening ? (
                <>
                  <div className="w-3.5 h-3.5 border-2 border-white/30 border-t-white rounded-full animate-spin" />
                  <span>Synthesizing Counter-Rule...</span>
                </>
              ) : (
                <>
                  <ShieldCheck className="w-3.5 h-3.5" />
                  <span>Launch Attack & Harden Gate</span>
                </>
              )}
            </button>
          </div>
        </div>

        {/* Hardening Success Alert */}
        {latestHardeningSuccess && (
          <div className="p-4 rounded-lg border border-indigo-700/60 bg-indigo-950/40 text-xs font-mono">
            <div className="flex items-center gap-2 text-indigo-300 font-bold mb-1">
              <CheckCircle2 className="w-4 h-4 text-emerald-400" />
              <span>Gate Self-Hardened: {latestHardeningSuccess.newGateVersion} Deployed</span>
            </div>
            <div className="text-slate-300 text-[11px] space-y-1">
              <div>Neutralized: {latestHardeningSuccess.attackVector}</div>
              <div>Generated Invariant Rule: <strong className="text-indigo-200">{latestHardeningSuccess.synthesizedRuleId}</strong> ({latestHardeningSuccess.synthesizedRuleName})</div>
              <div className="text-emerald-400 font-semibold">
                Benchmark Verification: Catch Rate improved {latestHardeningSuccess.preCatchRate.toFixed(1)}% → {latestHardeningSuccess.postCatchRate.toFixed(1)}% with zero false block degradation!
              </div>
            </div>
          </div>
        )}

        {/* Recent Hardening Ledger */}
        <div className="space-y-2 pt-1">
          <div className="text-[11px] font-mono text-slate-400 font-semibold">
            Recent Hardening Events:
          </div>
          <div className="space-y-1.5">
            {hardeningEvents.slice(0, 3).map((event, idx) => (
              <div key={idx} className="bg-slate-950/60 p-2.5 rounded border border-slate-800 text-[11px] font-mono flex items-center justify-between">
                <div>
                  <span className="text-indigo-400 font-bold">{event.synthesizedRuleId}</span>
                  <span className="text-slate-500 mx-1.5">·</span>
                  <span className="text-slate-300">{event.attackerTechnique}</span>
                </div>
                <div className="flex items-center gap-2">
                  <span className="text-emerald-400 font-semibold">{event.postCatchRate}% catch</span>
                  <span className="px-1.5 py-0.5 rounded bg-indigo-900/40 text-indigo-300 text-[10px]">{event.newGateVersion}</span>
                </div>
              </div>
            ))}
          </div>
        </div>
      </div>

      {/* Gate Versions Table */}
      <div className="rounded-xl border border-slate-800 bg-slate-950 overflow-hidden font-mono text-xs">
        <div className="bg-slate-900/80 px-4 py-2.5 border-b border-slate-800 flex items-center justify-between">
          <div className="flex items-center gap-2">
            <History className="w-4 h-4 text-indigo-400" />
            <span className="font-bold text-slate-200">Gate Version Audit Ledger</span>
          </div>
          <span className="text-[11px] text-slate-500">Every version and score is permanently logged</span>
        </div>

        <div className="overflow-x-auto">
          <table className="w-full text-left">
            <thead className="bg-slate-900/40 text-[11px] text-slate-400 border-b border-slate-800">
              <tr>
                <th className="py-2.5 px-4 font-medium">Version</th>
                <th className="py-2.5 px-4 font-medium">Status</th>
                <th className="py-2.5 px-4 font-medium text-right">Catch Rate</th>
                <th className="py-2.5 px-4 font-medium text-right">False Blocks</th>
                <th className="py-2.5 px-4 font-medium text-right">Held-Out Tests</th>
                <th className="py-2.5 px-4 font-medium">Evolution Trigger / Changelog</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-800/60 text-slate-300">
              {versions.map((ver, idx) => (
                <tr key={idx} className="hover:bg-slate-900/50 transition-colors">
                  <td className="py-2.5 px-4 font-bold text-white whitespace-nowrap">
                    {ver.version}
                  </td>
                  <td className="py-2.5 px-4 whitespace-nowrap">
                    <span className={`px-2 py-0.5 rounded text-[10px] font-bold ${
                      ver.status === 'active'
                        ? 'bg-emerald-950 text-emerald-300 border border-emerald-800'
                        : ver.status === 'rolled_back'
                        ? 'bg-rose-950 text-rose-300 border border-rose-800'
                        : 'bg-slate-800 text-slate-400'
                    }`}>
                      {ver.status.toUpperCase()}
                    </span>
                  </td>
                  <td className="py-2.5 px-4 text-right text-emerald-400 font-semibold tabular-nums">
                    {ver.catchRate.toFixed(1)}%
                  </td>
                  <td className="py-2.5 px-4 text-right text-indigo-300 font-semibold tabular-nums">
                    {ver.falseBlockRate.toFixed(1)}%
                  </td>
                  <td className="py-2.5 px-4 text-right text-slate-400 tabular-nums">
                    {ver.heldOutTestCount}
                  </td>
                  <td className="py-2.5 px-4 text-[11px] text-slate-400 font-sans max-w-md">
                    {ver.changeNote}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
};
