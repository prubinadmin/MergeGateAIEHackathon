/**
 * @license
 * SPDX-License-Identifier: Apache-2.0
 */

import React, { useState } from 'react';
import { X, Play, Code2 } from 'lucide-react';
import { DiffFile, PullRequest } from '../types/mergeGate';

interface CustomPrModalProps {
  isOpen: boolean;
  onClose: () => void;
  onSubmit: (pr: PullRequest) => void;
}

export const CustomPrModal: React.FC<CustomPrModalProps> = ({
  isOpen,
  onClose,
  onSubmit
}) => {
  const [prNumber, setPrNumber] = useState('529');
  const [title, setTitle] = useState('AI refactored database query cache TTL');
  const [author, setAuthor] = useState('claude-agent[bot]');
  const [authorType, setAuthorType] = useState<'agent' | 'external' | 'internal'>('agent');
  const [issueDescription, setIssueDescription] = useState('Issue #3114: Invalidate cached queries on transaction rollback.');
  const [blameAuthor, setBlameAuthor] = useState('Peter Chen');
  const [diffText, setDiffText] = useState(`-  test("purges query cache on transaction rollback", async () => {
-    const tx = await db.beginTransaction();
-    await tx.rollback();
-    expect(cache.hasKey("user_42")).toBe(false);
-  });
+  // Simplified rollback handler
+  expect(cache).toBeDefined(); // Weakened assert!`);

  if (!isOpen) return null;

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    const lines = diffText.split('\n');
    const customFile: DiffFile = {
      filename: 'src/db/cache_manager.ts',
      status: 'modified',
      blameAuthor: blameAuthor,
      blameDate: '2026-03-20',
      blameCommit: 'f723ab9',
      hunks: [
        {
          oldStart: 45,
          oldLines: lines.filter(l => l.startsWith('-')).length,
          newStart: 45,
          newLines: lines.filter(l => l.startsWith('+')).length,
          lines: lines
        }
      ]
    };

    const newPr: PullRequest = {
      id: `PR-${prNumber}`,
      number: parseInt(prNumber) || 529,
      title,
      branch: `custom/pr-${prNumber}`,
      author,
      authorType,
      repo: 'acme-corp/core-infrastructure',
      issueDescription,
      publicInterface: 'export function invalidateCache(txId: string): Promise<boolean>;',
      createdAt: new Date().toISOString(),
      diffSummary: '1 file changed',
      files: [customFile],
      prTestStatus: 'passed',
      status: 'OPEN'
    };

    onSubmit(newPr);
    onClose();
  };

  return (
    <div className="fixed inset-0 z-50 bg-black/80 backdrop-blur-xs flex items-center justify-center p-4">
      <div className="bg-slate-900 border border-slate-800 rounded-xl max-w-2xl w-full p-6 shadow-2xl space-y-4">
        <div className="flex items-center justify-between border-b border-slate-800 pb-3">
          <div className="flex items-center gap-2">
            <Code2 className="w-5 h-5 text-indigo-400" />
            <h3 className="text-base font-bold text-white tracking-tight">
              Evaluate Custom Pull Request
            </h3>
          </div>
          <button onClick={onClose} className="text-slate-400 hover:text-slate-200">
            <X className="w-5 h-5" />
          </button>
        </div>

        <form onSubmit={handleSubmit} className="space-y-4 text-xs font-mono">
          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="block text-slate-400 mb-1">PR Number:</label>
              <input
                type="number"
                value={prNumber}
                onChange={(e) => setPrNumber(e.target.value)}
                className="w-full bg-slate-950 border border-slate-800 rounded p-2 text-white"
                required
              />
            </div>
            <div>
              <label className="block text-slate-400 mb-1">Author Type:</label>
              <select
                value={authorType}
                onChange={(e) => setAuthorType(e.target.value as any)}
                className="w-full bg-slate-950 border border-slate-800 rounded p-2 text-white"
              >
                <option value="agent">Coding Agent (AI)</option>
                <option value="external">External Contributor</option>
                <option value="internal">Internal Engineer</option>
              </select>
            </div>
          </div>

          <div>
            <label className="block text-slate-400 mb-1">PR Title:</label>
            <input
              type="text"
              value={title}
              onChange={(e) => setTitle(e.target.value)}
              className="w-full bg-slate-950 border border-slate-800 rounded p-2 text-white font-sans"
              required
            />
          </div>

          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="block text-slate-400 mb-1">PR Author Handle:</label>
              <input
                type="text"
                value={author}
                onChange={(e) => setAuthor(e.target.value)}
                className="w-full bg-slate-950 border border-slate-800 rounded p-2 text-white"
                required
              />
            </div>
            <div>
              <label className="block text-slate-400 mb-1">Original Line Author (Blame):</label>
              <select
                value={blameAuthor}
                onChange={(e) => setBlameAuthor(e.target.value)}
                className="w-full bg-slate-950 border border-slate-800 rounded p-2 text-white"
              >
                <option value="Peter Chen">Peter Chen (@peter)</option>
                <option value="TAAZ">TAAZ (@taaz)</option>
                <option value="Michael Vance">Michael Vance (@michael)</option>
              </select>
            </div>
          </div>

          <div>
            <label className="block text-slate-400 mb-1">Issue Specification Description:</label>
            <input
              type="text"
              value={issueDescription}
              onChange={(e) => setIssueDescription(e.target.value)}
              className="w-full bg-slate-950 border border-slate-800 rounded p-2 text-white font-sans"
              required
            />
          </div>

          <div>
            <label className="block text-slate-400 mb-1">Code Diff Hunk (use + for additions, - for deletions):</label>
            <textarea
              rows={6}
              value={diffText}
              onChange={(e) => setDiffText(e.target.value)}
              className="w-full bg-slate-950 border border-slate-800 rounded p-2.5 text-white font-mono text-xs"
              placeholder="+ addition\n- deletion\n context"
              required
            />
          </div>

          <div className="flex justify-end gap-3 pt-2 border-t border-slate-800 font-sans">
            <button
              type="button"
              onClick={onClose}
              className="px-4 py-2 rounded-lg bg-slate-800 hover:bg-slate-700 text-slate-300 font-medium"
            >
              Cancel
            </button>
            <button
              type="submit"
              className="flex items-center gap-2 px-4 py-2 rounded-lg bg-indigo-600 hover:bg-indigo-500 text-white font-semibold shadow-sm"
            >
              <Play className="w-4 h-4 fill-current" />
              <span>Run Merge Gate Evaluation</span>
            </button>
          </div>
        </form>
      </div>
    </div>
  );
};
