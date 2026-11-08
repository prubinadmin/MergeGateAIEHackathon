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
      <div className="flex items-center justify-between border-b border-yellow-500/20 pb-2">
        <div className="flex items-center gap-2 overflow-x-auto">
          {pr.files.map((file, idx) => (
            <button
              key={file.filename}
              onClick={() => setSelectedFileIndex(idx)}
              className={`flex items-center gap-2 px-3 py-1.5 text-xs font-mono rounded-md transition-all ${
                selectedFileIndex === idx
                  ? 'bg-yellow-400 text-black font-bold border border-yellow-500'
                  : 'text-neutral-400 hover:text-yellow-300'
              }`}
            >
              <FileCode className={`w-3.5 h-3.5 ${selectedFileIndex === idx ? 'text-black' : 'text-yellow-400'}`} />
              <span>{file.filename}</span>
            </button>
          ))}
        </div>

        {/* File Blame Summary */}
        <div className="hidden sm:flex items-center gap-2 text-xs text-neutral-400 font-mono bg-neutral-950 px-3 py-1 rounded border border-yellow-500/20">
          <UserCheck className="w-3.5 h-3.5 text-yellow-400" />
          <span>Base Line Owner: <strong className="text-yellow-400">{activeFile?.blameAuthor}</strong> ({activeFile?.blameDate})</span>
          <span className="text-neutral-600">·</span>
          <span className="text-neutral-500">#{activeFile?.blameCommit}</span>
        </div>
      </div>

      {/* Code Diff Table */}
      <div className="rounded-xl border border-yellow-500/20 bg-black overflow-hidden font-mono text-xs">
        {/* Table Header */}
        <div className="bg-neutral-950 px-4 py-2 border-b border-neutral-800 flex items-center justify-between text-neutral-400">
          <div className="flex items-center gap-2">
            <span className="text-yellow-400 font-bold">{activeFile?.filename}</span>
            <span className="text-neutral-500">({activeFile?.status})</span>
          </div>
          <div className="text-[11px] text-neutral-500">
            Unified Line-Blame Inspection View
          </div>
        </div>

        {/* Hunks */}
        <div className="divide-y divide-neutral-900">
          {activeFile?.hunks.map((hunk, hIdx) => {
            let oldLineNum = hunk.oldStart;
            let newLineNum = hunk.newStart;

            return (
              <div key={hIdx} className="overflow-x-auto">
                {/* Hunk Header */}
                <div className="bg-yellow-500/10 text-yellow-300 px-4 py-1 text-[11px] font-mono border-y border-yellow-500/30">
                  @@ -{hunk.oldStart},{hunk.oldLines} +{hunk.newStart},{hunk.newLines} @@
                </div>

                {/* Hunk Lines */}
                <div className="divide-y divide-neutral-900/60">
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
                          className={`flex items-stretch hover:bg-neutral-950 transition-colors ${
                            isAddition
                              ? 'bg-emerald-950/25 text-emerald-200'
                              : isDeletion
                              ? 'bg-rose-950/25 text-rose-300'
                              : 'text-neutral-300'
                          }`}
                        >
                          {/* Line Numbers */}
                          <div className="w-12 py-1 px-2 text-right text-[11px] text-neutral-600 select-none border-r border-neutral-900 bg-black shrink-0 tabular-nums">
                            {currentOldNum ?? ''}
                          </div>
                          <div className="w-12 py-1 px-2 text-right text-[11px] text-neutral-600 select-none border-r border-neutral-900 bg-black shrink-0 tabular-nums">
                            {currentNewNum ?? ''}
                          </div>

                          {/* Line Blame Tag (for base/deleted lines) */}
                          <div className="hidden md:block w-36 py-1 px-2 text-[10px] text-neutral-500 border-r border-neutral-900 truncate shrink-0 select-none">
                            {isDeletion || !isAddition ? (
                              <span title={`${activeFile.blameAuthor} on ${activeFile.blameDate}`}>
                                {activeFile.blameAuthor} · {activeFile.blameDate}
                              </span>
                            ) : (
                              <span className="text-yellow-400 italic">PR Addition</span>
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
                          <div className="bg-yellow-500/15 border-y border-yellow-500/50 px-4 py-2 text-yellow-200 flex items-start gap-2.5">
                            <AlertOctagon className="w-4 h-4 text-yellow-400 shrink-0 mt-0.5" />
                            <div>
                              <div className="font-bold font-mono text-xs text-yellow-300">
                                ANTI-GAMING VIOLATION: {matchingViolation.ruleId} ({matchingViolation.ruleName})
                              </div>
                              <div className="text-[11px] text-neutral-200 font-sans mt-0.5">
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
