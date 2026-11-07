/**
 * @license
 * SPDX-License-Identifier: Apache-2.0
 */

import React, { useState } from 'react';
import { FileCode, AlertOctagon, GitCommit, UserCheck } from 'lucide-react';
import { AntiGamingViolation, DiffFile, PullRequest } from '../types/mergeGate';

interface DiffViewerProps {
  pr: PullRequest;
  violations: AntiGamingViolation[];
}

export const DiffViewer: React.FC<DiffViewerProps> = ({ pr, violations }) => {
  const [selectedFileIndex, setSelectedFileIndex] = useState(0);
  const activeFile: DiffFile = pr.files[selectedFileIndex] || pr.files[0];

  return (
    <div className="space-y-4">
      {/* File Selector Tabs */}
      <div className="flex items-center justify-between border-b border-slate-800 pb-2">
        <div className="flex items-center gap-2 overflow-x-auto">
          {pr.files.map((file, idx) => (
            <button
              key={file.filename}
              onClick={() => setSelectedFileIndex(idx)}
              className={`flex items-center gap-2 px-3 py-1.5 text-xs font-mono rounded-md transition-all ${
                selectedFileIndex === idx
                  ? 'bg-slate-800 text-white border border-slate-700'
                  : 'text-slate-400 hover:text-slate-200'
              }`}
            >
              <FileCode className="w-3.5 h-3.5 text-indigo-400" />
              <span>{file.filename}</span>
            </button>
          ))}
        </div>

        {/* File Blame Summary */}
        <div className="hidden sm:flex items-center gap-2 text-xs text-slate-400 font-mono bg-slate-900 px-3 py-1 rounded border border-slate-800">
          <UserCheck className="w-3.5 h-3.5 text-indigo-400" />
          <span>Base Line Owner: <strong className="text-slate-200">{activeFile?.blameAuthor}</strong> ({activeFile?.blameDate})</span>
          <span className="text-slate-600">·</span>
          <span className="text-slate-500">#{activeFile?.blameCommit}</span>
        </div>
      </div>

      {/* Code Diff Table */}
      <div className="rounded-xl border border-slate-800 bg-slate-950 overflow-hidden font-mono text-xs">
        {/* Table Header */}
        <div className="bg-slate-900/80 px-4 py-2 border-b border-slate-800 flex items-center justify-between text-slate-400">
          <div className="flex items-center gap-2">
            <span className="text-slate-200 font-bold">{activeFile?.filename}</span>
            <span className="text-slate-500">({activeFile?.status})</span>
          </div>
          <div className="text-[11px] text-slate-500">
            Unified Line-Blame Inspection View
          </div>
        </div>

        {/* Hunks */}
        <div className="divide-y divide-slate-850">
          {activeFile?.hunks.map((hunk, hIdx) => {
            let oldLineNum = hunk.oldStart;
            let newLineNum = hunk.newStart;

            return (
              <div key={hIdx} className="overflow-x-auto">
                {/* Hunk Header */}
                <div className="bg-indigo-950/20 text-indigo-300 px-4 py-1 text-[11px] font-mono border-y border-indigo-900/30">
                  @@ -{hunk.oldStart},{hunk.oldLines} +{hunk.newStart},{hunk.newLines} @@
                </div>

                {/* Hunk Lines */}
                <div className="divide-y divide-slate-900/40">
                  {hunk.lines.map((line, lIdx) => {
                    const isAddition = line.startsWith('+');
                    const isDeletion = line.startsWith('-');
                    const lineContent = line.substring(1);

                    const currentOldNum = !isAddition ? oldLineNum++ : null;
                    const currentNewNum = !isDeletion ? newLineNum++ : null;

                    // Check if this line triggered an anti-gaming violation
                    const matchingViolation = violations.find(
                      v => v.file === activeFile.filename && (
                        (v.snippet && line.includes(v.snippet.trim())) ||
                        (v.line && currentNewNum === v.line)
                      )
                    );

                    return (
                      <React.Fragment key={lIdx}>
                        <div
                          className={`flex items-stretch hover:bg-slate-900/60 transition-colors ${
                            isAddition
                              ? 'bg-emerald-950/25 text-emerald-200'
                              : isDeletion
                              ? 'bg-rose-950/25 text-rose-300'
                              : 'text-slate-300'
                          }`}
                        >
                          {/* Line Numbers */}
                          <div className="w-12 py-1 px-2 text-right text-[11px] text-slate-600 select-none border-r border-slate-850 bg-slate-950/40 shrink-0 tabular-nums">
                            {currentOldNum ?? ''}
                          </div>
                          <div className="w-12 py-1 px-2 text-right text-[11px] text-slate-600 select-none border-r border-slate-850 bg-slate-950/40 shrink-0 tabular-nums">
                            {currentNewNum ?? ''}
                          </div>

                          {/* Line Blame Tag (for base/deleted lines) */}
                          <div className="hidden md:block w-36 py-1 px-2 text-[10px] text-slate-500 border-r border-slate-850/60 truncate shrink-0 select-none">
                            {isDeletion || !isAddition ? (
                              <span title={`${activeFile.blameAuthor} on ${activeFile.blameDate}`}>
                                {activeFile.blameAuthor} · {activeFile.blameDate}
                              </span>
                            ) : (
                              <span className="text-indigo-400 italic">PR Addition</span>
                            )}
                          </div>

                          {/* Sign & Code Content */}
                          <div className="w-6 py-1 text-center font-bold select-none shrink-0">
                            {line.charAt(0)}
                          </div>
                          <div className="py-1 px-2 flex-1 whitespace-pre overflow-x-auto">
                            {lineContent}
                          </div>
                        </div>

                        {/* Inline Violation Warning Banner */}
                        {matchingViolation && (
                          <div className="bg-rose-950/60 border-y border-rose-700/60 px-4 py-2 text-rose-200 flex items-start gap-2.5">
                            <AlertOctagon className="w-4 h-4 text-rose-400 shrink-0 mt-0.5" />
                            <div>
                              <div className="font-bold font-mono text-xs text-rose-300">
                                ANTI-GAMING VIOLATION: {matchingViolation.ruleId} ({matchingViolation.ruleName})
                              </div>
                              <div className="text-[11px] text-slate-300 font-sans mt-0.5">
                                {matchingViolation.description}
                              </div>
                            </div>
                          </div>
                        )}
                      </React.Fragment>
                    );
                  })}
                </div>
              </div>
            );
          })}
        </div>
      </div>
    </div>
  );
};
