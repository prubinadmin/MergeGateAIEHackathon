/**
 * @license
 * SPDX-License-Identifier: Apache-2.0
 * 
 * Merge Gate Reviewer - Main Application
 * Built by Michael, TAAZ and Peter at AIE Code Summit 2026 Hackathon (Shack15 SF)
 */

import React, { useState, useEffect, useCallback } from 'react';
import { Header } from './components/Header';
import { ScenarioBar } from './components/ScenarioBar';
import { PipelineVisualizer } from './components/PipelineVisualizer';
import { PhoneSimulator } from './components/PhoneSimulator';
import { DiffViewer } from './components/DiffViewer';
import { ContractJsonViewer } from './components/ContractJsonViewer';
import { LearningTrackView } from './components/LearningTrackView';
import { StarterCodeView } from './components/StarterCodeView';
import { CustomPrModal } from './components/CustomPrModal';

import { DEMO_SCENARIOS } from './services/scenarios';
import { calculateOwnerAttribution } from './services/ownerDiscovery';
import { runAntiGamingChecks } from './services/antiGamingRules';
import { generateIndependentTests } from './services/independentRunner';
import { runAiTestVerifierAgent } from './services/aiTestAgent';
import { evaluateMergeGate } from './services/verdictEngine';
import { INITIAL_GATE_VERSIONS } from './services/learningEngine';

import {
  AiAgentVerificationReport,
  AntiGamingViolation,
  CodeOwner,
  GateRuleVersion,
  IndependentTestCase,
  MergeGateResult,
  PhoneMessage,
  PullRequest
} from './types/mergeGate';

export default function App() {
  const [activeTab, setActiveTab] = useState<'pipeline' | 'diff' | 'phone' | 'learning' | 'starter-code'>('pipeline');
  const [scenarios, setScenarios] = useState<PullRequest[]>(DEMO_SCENARIOS);
  const [selectedPr, setSelectedPr] = useState<PullRequest>(DEMO_SCENARIOS[0]);
  const [owners, setOwners] = useState<CodeOwner[]>([]);
  const [antiGamingViolations, setAntiGamingViolations] = useState<AntiGamingViolation[]>([]);
  const [independentTests, setIndependentTests] = useState<IndependentTestCase[]>([]);
  const [gateResult, setGateResult] = useState<MergeGateResult | null>(null);
  const [aiAgentReport, setAiAgentReport] = useState<AiAgentVerificationReport | null>(null);
  const [isAiAgentRunning, setIsAiAgentRunning] = useState(false);
  const [isRunning, setIsRunning] = useState(false);
  const [isCustomModalOpen, setIsCustomModalOpen] = useState(false);
  const [gateVersions, setGateVersions] = useState<GateRuleVersion[]>(INITIAL_GATE_VERSIONS);
  const [messages, setMessages] = useState<PhoneMessage[]>([]);
  const [prStatus, setPrStatus] = useState<string>('OPEN');

  // Helper to merge deterministic AST violations with unique AI-Agent-discovered violations without duplicates
  const mergeViolations = (
    baseViolations: AntiGamingViolation[],
    agentViolations: AntiGamingViolation[]
  ): AntiGamingViolation[] => {
    const merged = [...baseViolations];
    for (const av of agentViolations) {
      const exists = merged.some(
        bv =>
          bv.file === av.file &&
          bv.ruleId === av.ruleId &&
          Math.abs(bv.line - av.line) <= 3
      );
      if (!exists) {
        merged.push(av);
      }
    }
    return merged;
  };

  // Run the AI Test Verifier Agent to synthesize dynamic tests & unique defect suggestions
  const executeAiAgentForPr = useCallback(
    async (
      pr: PullRequest,
      allOwners: CodeOwner[],
      baseViolations: AntiGamingViolation[]
    ) => {
      setIsAiAgentRunning(true);
      try {
        const report = await runAiTestVerifierAgent(pr);
        setAiAgentReport(report);

        const combinedViolations = mergeViolations(baseViolations, report.detectedViolations);
        const finalTests =
          report.synthesizedTests.length > 0
            ? report.synthesizedTests
            : generateIndependentTests(pr);

        setAntiGamingViolations(combinedViolations);
        setIndependentTests(finalTests);

        const updatedResult = await evaluateMergeGate(pr, allOwners, combinedViolations, finalTests);
        setGateResult(updatedResult);
        setPrStatus(
          pr.status === 'BLOCKED'
            ? 'BLOCKED'
            : updatedResult.verdict === 'BLOCK'
            ? 'OPEN (BLOCKED RECOMMENDED)'
            : 'OPEN'
        );

        const primaryOwner = allOwners[0] || { name: 'Peter Chen', phone: '+1 415-555-0142', lines: 1, last_touched: '2026-03-14' };
        const initialMsg: PhoneMessage = {
          id: `msg-${Date.now()}`,
          prId: pr.id,
          recipientName: primaryOwner.name,
          recipientPhone: primaryOwner.phone || '+1 415-555-0142',
          sender: 'merge-gate',
          body: updatedResult.summary,
          timestamp: '11:58 AM',
          evidenceLink:
            updatedResult.verdict === 'BLOCK'
              ? 'https://merge-gate.internal/runs/' + updatedResult.run_hash
              : undefined
        };
        setMessages([initialMsg]);
      } finally {
        setIsAiAgentRunning(false);
      }
    },
    []
  );

  // Evaluate the pipeline for the given PR (instant generic AST pass + live AI Test Agent pass)
  const evaluatePr = useCallback(async (pr: PullRequest) => {
    setIsRunning(true);

    // 1. Owner discovery via line blame and recency decay
    const { primaryOwner, allOwners } = calculateOwnerAttribution(pr.files);
    setOwners(allOwners);

    // 2. Deterministic + Generic AST checks
    const violations = runAntiGamingChecks(pr.files, pr.issueDescription);
    setAntiGamingViolations(violations);

    // 3. Generic Function-Extracted Independent Tests (no hardcoded PR IDs)
    const tests = generateIndependentTests(pr);
    setIndependentTests(tests);

    // 4. Deterministic verdict calculation
    const result = await evaluateMergeGate(pr, allOwners, violations, tests);
    setGateResult(result);
    setPrStatus(pr.status || (result.verdict === 'BLOCK' ? 'OPEN (BLOCKED RECOMMENDED)' : 'OPEN'));

    // 5. Initial iMessage to the line owner
    const initialMsg: PhoneMessage = {
      id: `msg-${Date.now()}`,
      prId: pr.id,
      recipientName: primaryOwner.name,
      recipientPhone: primaryOwner.phone || '+1 415-555-0142',
      sender: 'merge-gate',
      body: result.summary,
      timestamp: '11:58 AM',
      evidenceLink: result.verdict === 'BLOCK' ? 'https://merge-gate.internal/runs/' + result.run_hash : undefined
    };

    setMessages([initialMsg]);
    setIsRunning(false);

    // 6. Trigger live AI Test Agent to synthesize deeper scenario-specific tests & refactoring suggestions
    executeAiAgentForPr(pr, allOwners, violations);
  }, [executeAiAgentForPr]);

  // Run on initial load and when switching PR
  useEffect(() => {
    evaluatePr(selectedPr);
  }, [selectedPr, evaluatePr]);

  // Handle owner SMS replies (BLOCK, WHY, OK, FALSE ALARM)
  const handleOwnerMessage = (userText: string) => {
    const cmd = userText.trim().toUpperCase();
    const primaryOwner = owners[0] || { name: 'Peter', phone: '+1 415-555-0142' };

    // Add owner message to stream
    const userMsg: PhoneMessage = {
      id: `msg-${Date.now()}`,
      prId: selectedPr.id,
      recipientName: primaryOwner.name,
      recipientPhone: primaryOwner.phone || '+1 415-555-0142',
      sender: 'owner',
      body: userText,
      timestamp: 'Just now'
    };

    const newMessages = [...messages, userMsg];

    // Determine system bot reply based on rules
    let botReplyText = '';

    if (cmd === 'BLOCK') {
      setPrStatus('BLOCKED');
      botReplyText = `PR #${selectedPr.number} has been BLOCKED on GitHub by your authorization (${primaryOwner.name}). Merge pipelines are frozen. Run hash: ${gateResult?.run_hash.slice(0, 12)}.`;
    } else if (cmd === 'WHY') {
      if (antiGamingViolations.length > 0 && independentTests.some(t => !t.passed)) {
        const topViolation = antiGamingViolations[0];
        const failingTest = independentTests.find(t => !t.passed);
        botReplyText = `Failure breakdown:\n1. Rule ${topViolation.ruleId} (${topViolation.ruleName}): ${topViolation.description}\n2. Independent test ${failingTest?.id} (${failingTest?.name}): Expected ${failingTest?.expected}, got ${failingTest?.actual}.`;
      } else if (independentTests.some(t => !t.passed)) {
        const failingTest = independentTests.find(t => !t.passed);
        botReplyText = `Failing Independent Test: ${failingTest?.id} (${failingTest?.name})\nExpected: ${failingTest?.expected}\nActual: ${failingTest?.actual}\nTrace: ${failingTest?.errorTrace || 'Assertion failed in sandbox'}`;
      } else if (antiGamingViolations.length > 0) {
        const topViolation = antiGamingViolations[0];
        botReplyText = `Anti-gaming violation triggered: ${topViolation.ruleId} - ${topViolation.description} at ${topViolation.file}:${topViolation.line}.`;
      } else {
        botReplyText = `No defects detected. All independent tests passed and zero anti-gaming rules triggered.`;
      }
    } else if (cmd === 'OK') {
      botReplyText = `Design Rule: Easy to stop, hard to approve.\nA text message alone can never approve or merge. Complete your review with your engineer credentials on GitHub: https://github.com/${selectedPr.repo}/pull/${selectedPr.number}#review`;
    } else if (cmd === 'FALSE ALARM') {
      botReplyText = `Logged FALSE ALARM from ${primaryOwner.name} for PR #${selectedPr.number}. Proposed Gate vN+1 benchmark triggered against 310 held-out historical PRs in Learning Track.`;
    } else {
      botReplyText = `Merge Gate Command Menu:\n• Reply BLOCK to freeze PR\n• Reply WHY for failing test trace\n• Reply OK for GitHub review link\n• Reply FALSE ALARM to tune rules`;
    }

    const botMsg: PhoneMessage = {
      id: `msg-${Date.now() + 1}`,
      prId: selectedPr.id,
      recipientName: primaryOwner.name,
      recipientPhone: primaryOwner.phone || '+1 415-555-0142',
      sender: 'merge-gate',
      body: botReplyText,
      timestamp: 'Just now'
    };

    setMessages([...newMessages, botMsg]);
  };

  const handleResetMessages = () => {
    if (gateResult) {
      const primaryOwner = owners[0] || { name: 'Peter', phone: '+1 415-555-0142' };
      setMessages([
        {
          id: `msg-${Date.now()}`,
          prId: selectedPr.id,
          recipientName: primaryOwner.name,
          recipientPhone: primaryOwner.phone || '+1 415-555-0142',
          sender: 'merge-gate',
          body: gateResult.summary,
          timestamp: '11:58 AM',
          evidenceLink: gateResult.verdict === 'BLOCK' ? 'https://merge-gate.internal/runs/' + gateResult.run_hash : undefined
        }
      ]);
    }
  };

  const handleCustomPrSubmit = (customPr: PullRequest) => {
    setScenarios(prev => {
      const filtered = prev.filter(item => item.id !== customPr.id);
      return [customPr, ...filtered];
    });
    setSelectedPr(customPr);
  };

  return (
    <div className="flex-1 bg-slate-950 text-slate-100 flex flex-col font-sans">
      {/* Top Header */}
      <Header
        activeTab={activeTab}
        setActiveTab={setActiveTab}
        onRunEval={() => evaluatePr(selectedPr)}
        isRunning={isRunning || isAiAgentRunning}
        currentVerdict={gateResult?.verdict}
      />

      {/* Demo Scenario Selector & Live GitHub Link Analyzer Bar */}
      <ScenarioBar
        scenarios={scenarios}
        selectedPr={selectedPr}
        onSelectPr={(pr) => setSelectedPr(pr)}
        onOpenCustomModal={() => setIsCustomModalOpen(true)}
        onGitHubPrAnalyzed={handleCustomPrSubmit}
      />

      {/* Main Content Area */}
      <main className="flex-1 max-w-7xl w-full mx-auto p-6">
        {activeTab === 'pipeline' && (
          <div className="space-y-6">
            <PipelineVisualizer
              pr={selectedPr}
              owners={owners}
              antiGamingViolations={antiGamingViolations}
              independentTests={independentTests}
              gateResult={gateResult}
              aiAgentReport={aiAgentReport}
              isAiAgentRunning={isAiAgentRunning}
              onRunAiAgent={() => executeAiAgentForPr(selectedPr, owners, runAntiGamingChecks(selectedPr.files, selectedPr.issueDescription))}
              onNavigateToPhone={() => setActiveTab('phone')}
              onNavigateToDiff={() => setActiveTab('diff')}
              onNavigateToCode={() => setActiveTab('starter-code')}
            />

            {/* Owner Contract JSON Display */}
            <ContractJsonViewer gateResult={gateResult} />
          </div>
        )}

        {activeTab === 'phone' && (
          <PhoneSimulator
            pr={selectedPr}
            owner={owners[0] || { name: 'Peter Chen', lines: 42, last_touched: '2026-03-14' }}
            gateResult={gateResult}
            messages={messages}
            onSendMessage={handleOwnerMessage}
            onResetMessages={handleResetMessages}
            prStatus={prStatus}
          />
        )}

        {activeTab === 'diff' && (
          <div className="space-y-6">
            <div className="rounded-xl border border-slate-800 bg-slate-900/40 p-5">
              <h3 className="text-base font-bold text-white tracking-tight mb-1">
                Diff &amp; Line-Level Git Blame Inspector
              </h3>
              <p className="text-xs text-slate-400">
                Shows exact lines touched, with the original author blamed on each base line.
                Anti-gaming violations and AI-detected defects are highlighted directly inline on the affected code.
              </p>
            </div>
            <DiffViewer pr={selectedPr} violations={antiGamingViolations} />
          </div>
        )}

        {activeTab === 'learning' && (
          <LearningTrackView
            versions={gateVersions}
            onUpdateVersions={setGateVersions}
          />
        )}

        {activeTab === 'starter-code' && (
          <StarterCodeView />
        )}
      </main>

      {/* Footer */}
      <footer className="border-t border-slate-800/80 bg-slate-950 py-4 px-6 text-xs text-slate-500 flex flex-col sm:flex-row items-center justify-between gap-2">
        <div className="flex items-center gap-2">
          <span className="font-semibold text-slate-400">Merge Gate Reviewer</span>
          <span>·</span>
          <span>AIE Code Summit 2026 Hackathon · Shack15 SF</span>
        </div>
        <div className="font-mono text-[11px] text-slate-500">
          Easy to stop, hard to approve
        </div>
      </footer>

      {/* Custom PR Modal */}
      <CustomPrModal
        isOpen={isCustomModalOpen}
        onClose={() => setIsCustomModalOpen(false)}
        onSubmit={handleCustomPrSubmit}
      />
    </div>
  );
}
