/**
 * @license
 * SPDX-License-Identifier: Apache-2.0
 */

import React, { useState } from 'react';
import {
  FileCode,
  AlertOctagon,
  CheckCircle2,
  XCircle,
  AlertTriangle,
  Play,
  Copy,
  Check,
  FolderOpen,
  ArrowRight,
  ShieldAlert,
  Zap,
  Cpu,
  UserCheck
} from 'lucide-react';
import { TEST_SUITE_FILES, TestCaseFile } from '../services/testCasesData';

export const TestCasesView: React.FC = () => {
  const [selectedFileId, setSelectedFileId] = useState<string>(TEST_SUITE_FILES[0].id);
  const [analyzingFileId, setAnalyzingFileId] = useState<string | null>(null);
  const [isBatchRunning, setIsBatchRunning] = useState(false);
  const [analyzedFiles, setAnalyzedFiles] = useState<Record<string, boolean>>({
    'TC-01': true,
    'TC-02': true,
    'TC-03': true,
    'TC-04': true,
    'TC-05': true,
    'TC-06': true
  });
  const [copiedTicketId, setCopiedTicketId] = useState<string | null>(null);

  const activeFile = TEST_SUITE_FILES.find(f => f.id === selectedFileId) || TEST_SUITE_FILES[0];

  const handleRunAnalyzer = (fileId: string) => {
    setAnalyzingFileId(fileId);
    setTimeout(() => {
      setAnalyzedFiles(prev => ({ ...prev, [fileId]: true }));
      setAnalyzingFileId(null);
    }, 600);
  };

  const handleRunAll = () => {
    setIsBatchRunning(true);
    setTimeout(() => {
      const all: Record<string, boolean> = {};
      TEST_SUITE_FILES.forEach(f => { all[f.id] = true; });
      setAnalyzedFiles(all);
      setIsBatchRunning(false);
    }, 1200);
  };

  const handleCopyTicket = (file: TestCaseFile) => {
    const md = `## 🚨 [MERGE-GATE-${file.severity}] ${file.title}

**Target File:** \`test_cases/${file.filename}\`  
**Verdict:** \`${file.verdict}\` (Severity: \`${file.severity}\`)  
**Benchmark Category:** ${file.categoryLabel}  
**Original Line Owner Paged:** ${file.ownerPaged}  

### ⚠️ Why this AI code is unsafe:
${file.whyUnsafe}

### 🔍 Violations Detected:
${file.violations.map(v => `- **Line ${v.line}** [\`${v.ruleId}\`]: ${v.description}`).join('\n') || '- None (Clean conforming code)'}

### 🛠️ Recommended Remediation:
${file.remediation}

\`\`\`python
${file.safeRefactorSnippet}
\`\`\`
`;
    navigator.clipboard.writeText(md);
    setCopiedTicketId(file.id);
    setTimeout(() => setCopiedTicketId(null), 2000);
  };

  return (
    <div className="space-y-6">
      {/* Intro Header */}
      <div className="rounded-xl border border-slate-800 bg-slate-900/40 p-5 space-y-3">
        <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
          <div className="flex items-center gap-2 text-indigo-400">
            <FolderOpen className="w-5 h-5" />
            <h3 className="text-base font-bold text-white tracking-tight">
              Test Suite: Unsafe AI Code Detection & Issue Ticket Generator
            </h3>
          </div>

          <button
            onClick={handleRunAll}
            disabled={isBatchRunning}
            className="flex items-center gap-2 px-3.5 py-1.5 text-xs font-semibold text-white bg-indigo-600 hover:bg-indigo-500 disabled:opacity-50 rounded-lg shadow-sm transition-all shrink-0"
          >
            {isBatchRunning ? (
              <>
                <div className="w-3.5 h-3.5 border-2 border-white/30 border-t-white rounded-full animate-spin" />
                <span>Analyzing All 6 Test Files...</span>
              </>
            ) : (
              <>
                <Play className="w-3.5 h-3.5 fill-current" />
                <span>Run Analyzer on All Files</span>
              </>
            )}
          </button>
        </div>

        <p className="text-xs text-slate-300 leading-relaxed max-w-4xl">
          This test suite located in <code className="text-indigo-300 bg-slate-950 px-1.5 py-0.5 rounded border border-slate-800">test_cases/</code> contains
          isolated, reproducible code samples representing broken runtime execution, performance latency slowdowns,
          over-engineered cyclomatic complexity, style drift, regulatory violations, and clean conforming code.
          When analyzed, Merge Gate explains the exact safety risk and formats an actionable issue ticket for the engineer.
        </p>
      </div>

      {/* Grid: Left Column File Selector & Right Column Ticket Inspector */}
      <div className="grid grid-cols-1 lg:grid-cols-12 gap-6 items-start">
        {/* Left Column: File Tabs */}
        <div className="lg:col-span-4 space-y-2">
          <div className="text-[11px] font-mono text-slate-400 px-1 font-semibold uppercase tracking-wider">
            Test Suite Files ({TEST_SUITE_FILES.length})
          </div>

          <div className="space-y-2">
            {TEST_SUITE_FILES.map((file) => {
              const isSelected = file.id === selectedFileId;
              const isAnalyzing = analyzingFileId === file.id;

              return (
                <button
                  key={file.id}
                  onClick={() => setSelectedFileId(file.id)}
                  className={`w-full text-left p-3 rounded-xl border transition-all flex flex-col justify-between ${
                    isSelected
                      ? 'bg-slate-900 border-indigo-500/60 shadow-md ring-1 ring-indigo-500/20'
                      : 'bg-slate-950/60 hover:bg-slate-900/60 border-slate-800 hover:border-slate-700'
                  }`}
                >
                  <div className="flex items-center justify-between mb-1.5">
                    <div className="flex items-center gap-2">
                      <FileCode className={`w-4 h-4 ${
                        file.verdict === 'BLOCK' ? 'text-rose-400' : file.verdict === 'REVIEW' ? 'text-amber-400' : 'text-emerald-400'
                      }`} />
                      <span className="font-mono text-xs font-bold text-slate-200 truncate">
                        {file.filename}
                      </span>
                    </div>

                    <span className={`px-2 py-0.5 text-[10px] font-mono font-bold rounded ${
                      file.verdict === 'BLOCK'
                        ? 'bg-rose-950 text-rose-300 border border-rose-800/60'
                        : file.verdict === 'REVIEW'
                        ? 'bg-amber-950 text-amber-300 border border-amber-800/60'
                        : 'bg-emerald-950 text-emerald-300 border border-emerald-800/60'
                    }`}>
                      {file.verdict}
                    </span>
                  </div>

                  <p className="text-[11px] text-slate-400 truncate mb-2">
                    {file.title}
                  </p>

                  <div className="flex items-center justify-between pt-1 border-t border-slate-800/80 text-[10px] text-slate-500 font-mono">
                    <span>{file.categoryLabel.split('.')[1] || file.categoryLabel}</span>
                    <span className="text-slate-400">{file.violations.length} defects</span>
                  </div>
                </button>
              );
            })}
          </div>
        </div>

        {/* Right Column: Active File Inspection & Generated Issue Ticket */}
        <div className="lg:col-span-8 space-y-5">
          {/* Action Bar for Active File */}
          <div className="flex items-center justify-between bg-slate-900/80 p-3 rounded-xl border border-slate-800">
            <div className="flex items-center gap-2 font-mono text-xs text-slate-300">
              <span className="text-slate-500">Selected File:</span>
              <strong className="text-white">{activeFile.filename}</strong>
              <span className="text-slate-600">·</span>
              <span className="text-slate-400">Severity: {activeFile.severity}</span>
            </div>

            <div className="flex items-center gap-2">
              <button
                onClick={() => handleCopyTicket(activeFile)}
                className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs bg-slate-800 hover:bg-slate-700 text-slate-200 border border-slate-700 transition-colors"
              >
                {copiedTicketId === activeFile.id ? (
                  <>
                    <Check className="w-3.5 h-3.5 text-emerald-400" />
                    <span>Copied Markdown!</span>
                  </>
                ) : (
                  <>
                    <Copy className="w-3.5 h-3.5" />
                    <span>Copy Issue Ticket</span>
                  </>
                )}
              </button>

              <button
                onClick={() => handleRunAnalyzer(activeFile.id)}
                disabled={analyzingFileId === activeFile.id}
                className="flex items-center gap-1.5 px-3.5 py-1.5 rounded-lg text-xs font-semibold bg-indigo-600 hover:bg-indigo-500 disabled:opacity-50 text-white transition-all shadow-sm"
              >
                {analyzingFileId === activeFile.id ? (
                  <>
                    <div className="w-3.5 h-3.5 border-2 border-white/30 border-t-white rounded-full animate-spin" />
                    <span>Analyzing...</span>
                  </>
                ) : (
                  <>
                    <Play className="w-3.5 h-3.5 fill-current" />
                    <span>Re-Analyze File</span>
                  </>
                )}
              </button>
            </div>
          </div>

          {/* Generated Issue Ticket Card */}
          <div className="rounded-xl border border-slate-800 bg-slate-950 overflow-hidden shadow-lg">
            {/* Ticket Header */}
            <div className={`p-4 border-b flex items-center justify-between ${
              activeFile.verdict === 'BLOCK'
                ? 'bg-rose-950/40 border-rose-900/60'
                : activeFile.verdict === 'REVIEW'
                ? 'bg-amber-950/40 border-amber-900/60'
                : 'bg-emerald-950/40 border-emerald-900/60'
            }`}>
              <div className="flex items-center gap-3">
                {activeFile.verdict === 'BLOCK' ? (
                  <XCircle className="w-6 h-6 text-rose-400 shrink-0" />
                ) : activeFile.verdict === 'REVIEW' ? (
                  <AlertTriangle className="w-6 h-6 text-amber-400 shrink-0" />
                ) : (
                  <CheckCircle2 className="w-6 h-6 text-emerald-400 shrink-0" />
                )}
                <div>
                  <div className="text-[11px] font-mono text-slate-400">
                    MERGE-GATE ISSUE TICKET #{activeFile.id} · {activeFile.categoryLabel}
                  </div>
                  <h3 className="text-base font-bold text-white tracking-tight">
                    {activeFile.title}
                  </h3>
                </div>
              </div>

              <div className="text-right">
                <span className={`inline-block px-2.5 py-1 text-xs font-mono font-extrabold rounded ${
                  activeFile.verdict === 'BLOCK'
                    ? 'bg-rose-900/80 text-rose-200 border border-rose-700'
                    : activeFile.verdict === 'REVIEW'
                    ? 'bg-amber-900/80 text-amber-200 border border-amber-700'
                    : 'bg-emerald-900/80 text-emerald-200 border border-emerald-700'
                }`}>
                  VERDICT: {activeFile.verdict}
                </span>
                <div className="text-[10px] text-slate-400 mt-1 font-mono">
                  Owner: {activeFile.ownerPaged.split(' ')[0]}
                </div>
              </div>
            </div>

            {/* Ticket Body */}
            <div className="p-5 space-y-5 text-xs">
              {/* Why Unsafe Section */}
              <div className="space-y-1.5">
                <h4 className="text-xs font-mono font-bold text-slate-300 uppercase tracking-wider flex items-center gap-1.5">
                  <ShieldAlert className="w-4 h-4 text-indigo-400" />
                  Why This AI-Generated Code Is Unsafe:
                </h4>
                <p className="text-slate-300 text-xs leading-relaxed bg-slate-900/60 p-3.5 rounded-lg border border-slate-800">
                  {activeFile.whyUnsafe}
                </p>
              </div>

              {/* Detected Violations List */}
              <div className="space-y-2">
                <h4 className="text-xs font-mono font-bold text-slate-300 uppercase tracking-wider flex items-center justify-between">
                  <span className="flex items-center gap-1.5">
                    <AlertOctagon className="w-4 h-4 text-rose-400" />
                    Specific Violations Detected ({activeFile.violations.length})
                  </span>
                  <span className="text-[11px] text-slate-500 font-normal">
                    Deterministic AST & Style Invariants
                  </span>
                </h4>

                {activeFile.violations.length === 0 ? (
                  <div className="bg-emerald-950/20 border border-emerald-900/40 p-3 rounded-lg text-emerald-300 flex items-center gap-2">
                    <CheckCircle2 className="w-4 h-4 text-emerald-400" />
                    <span>0 violations detected. This code strictly adheres to runtime, performance, simplicity, and styling regulations.</span>
                  </div>
                ) : (
                  <div className="space-y-1.5 font-mono">
                    {activeFile.violations.map((v, i) => (
                      <div key={i} className="bg-slate-900/90 border border-slate-800 p-2.5 rounded flex items-start gap-2.5">
                        <span className="px-1.5 py-0.5 bg-rose-950 text-rose-300 text-[10px] font-bold rounded shrink-0">
                          {v.ruleId}
                        </span>
                        <span className="text-slate-500 shrink-0">Line {v.line}:</span>
                        <span className="text-slate-200">{v.description}</span>
                      </div>
                    ))}
                  </div>
                )}
              </div>

              {/* Code Comparison: Offending Code vs Safe Refactor */}
              <div className="grid grid-cols-1 md:grid-cols-2 gap-4 pt-1 font-mono">
                {/* Offending AI Code */}
                <div className="space-y-1.5">
                  <div className="text-[11px] font-bold text-rose-300 flex items-center justify-between">
                    <span>Offending AI Code in test_cases/{activeFile.filename}:</span>
                    <span className="text-[10px] text-rose-400/80">Blocked</span>
                  </div>
                  <div className="bg-slate-900 p-3 rounded-lg border border-slate-800 overflow-x-auto text-[11px] max-h-56 leading-relaxed text-slate-300">
                    <pre><code>{activeFile.code}</code></pre>
                  </div>
                </div>

                {/* Safe Refactor */}
                <div className="space-y-1.5">
                  <div className="text-[11px] font-bold text-emerald-300 flex items-center justify-between">
                    <span>Recommended Safe Refactor:</span>
                    <span className="text-[10px] text-emerald-400/80">Remediated</span>
                  </div>
                  <div className="bg-slate-900 p-3 rounded-lg border border-slate-800 overflow-x-auto text-[11px] max-h-56 leading-relaxed text-emerald-200/90">
                    <pre><code>{activeFile.safeRefactorSnippet}</code></pre>
                  </div>
                </div>
              </div>

              {/* Actionable Remediation Guidance */}
              <div className="border-t border-slate-800 pt-3 flex flex-col sm:flex-row items-start sm:items-center justify-between gap-3 text-xs">
                <div className="text-slate-400">
                  <strong className="text-slate-200">Action Required: </strong>
                  {activeFile.remediation}
                </div>
                <div className="text-[11px] font-mono text-slate-500 whitespace-nowrap">
                  Paging {activeFile.ownerPaged}
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
};
