/**
 * @license
 * SPDX-License-Identifier: Apache-2.0
 */

import React, { useState } from 'react';
import { Copy, Check, Download, Terminal, Code2, Cpu, Sparkles } from 'lucide-react';
import {
  PYTHON_STARTER_CODE,
  TYPESCRIPT_STARTER_CODE,
  GITHUB_ACTION_WORKFLOW
} from '../services/starterCodeTemplates';

export const StarterCodeView: React.FC = () => {
  const [selectedLanguage, setSelectedLanguage] = useState<'python' | 'typescript' | 'workflow'>('python');
  const [copied, setCopied] = useState(false);

  const getActiveCode = () => {
    switch (selectedLanguage) {
      case 'python':
        return { code: PYTHON_STARTER_CODE, filename: 'merge_gate.py', lang: 'python' };
      case 'typescript':
        return { code: TYPESCRIPT_STARTER_CODE, filename: 'merge-gate.ts', lang: 'typescript' };
      case 'workflow':
        return { code: GITHUB_ACTION_WORKFLOW, filename: 'merge-gate.yml', lang: 'yaml' };
    }
  };

  const active = getActiveCode();

  const handleCopy = () => {
    navigator.clipboard.writeText(active.code);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  const handleDownload = () => {
    const blob = new Blob([active.code], { type: 'text/plain' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = active.filename;
    a.click();
    URL.revokeObjectURL(url);
  };

  return (
    <div className="space-y-6">
      {/* Intro Header */}
      <div className="rounded-xl border border-yellow-500/20 bg-neutral-950 p-5 space-y-3">
        <div className="flex items-center gap-2 text-yellow-400">
          <Terminal className="w-5 h-5" />
          <h3 className="text-base font-bold text-white tracking-tight">
            Merge Gate Reviewer Starter Code & Deployment CLI
          </h3>
        </div>
        <p className="text-xs text-neutral-300 leading-relaxed max-w-4xl">
          Integrate Merge Gate into your engineering stack. These starter packages provide ready-to-run implementations
          of the deterministic anti-gaming checks, independent test sandbox runner, line-blame recency weighting,
          and the fixed owner JSON contract:
        </p>

        {/* Quick CLI Run Example */}
        <div className="bg-black p-3 rounded-lg border border-neutral-800 font-mono text-xs flex items-center justify-between">
          <div className="flex items-center gap-2 overflow-x-auto text-neutral-200">
            <span className="text-yellow-400 select-none">$</span>
            <span>python merge_gate.py --pr 412 --diff pr_412.diff --issue "Refactor tiered pricing"</span>
          </div>
          <span className="text-[11px] text-neutral-500 whitespace-nowrap ml-4">Outputs JSON Contract</span>
        </div>
      </div>

      {/* Code Viewer Panel */}
      <div className="rounded-xl border border-yellow-500/20 bg-black overflow-hidden font-mono text-xs">
        {/* Header Tabs */}
        <div className="bg-neutral-950 px-4 py-2 border-b border-neutral-800 flex items-center justify-between">
          <div className="flex items-center gap-2">
            <button
              onClick={() => setSelectedLanguage('python')}
              className={`px-3 py-1 rounded text-xs transition-colors ${
                selectedLanguage === 'python'
                  ? 'bg-yellow-400 text-black font-bold'
                  : 'text-neutral-400 hover:text-yellow-300'
              }`}
            >
              merge_gate.py (Python CLI)
            </button>
            <button
              onClick={() => setSelectedLanguage('typescript')}
              className={`px-3 py-1 rounded text-xs transition-colors ${
                selectedLanguage === 'typescript'
                  ? 'bg-yellow-400 text-black font-bold'
                  : 'text-neutral-400 hover:text-yellow-300'
              }`}
            >
              merge-gate.ts (Node/TS)
            </button>
            <button
              onClick={() => setSelectedLanguage('workflow')}
              className={`px-3 py-1 rounded text-xs transition-colors ${
                selectedLanguage === 'workflow'
                  ? 'bg-yellow-400 text-black font-bold'
                  : 'text-neutral-400 hover:text-yellow-300'
              }`}
            >
              .github/workflows/merge-gate.yml
            </button>
          </div>

          <div className="flex items-center gap-2">
            <button
              onClick={handleCopy}
              className="flex items-center gap-1.5 px-2.5 py-1 text-black font-bold bg-yellow-400 hover:bg-yellow-300 rounded transition-colors text-[11px]"
            >
              {copied ? (
                <>
                  <Check className="w-3.5 h-3.5 text-black" />
                  <span>Copied!</span>
                </>
              ) : (
                <>
                  <Copy className="w-3.5 h-3.5" />
                  <span>Copy Code</span>
                </>
              )}
            </button>

            <button
              onClick={handleDownload}
              className="flex items-center gap-1.5 px-2.5 py-1 text-yellow-400 hover:text-yellow-300 bg-neutral-900 hover:bg-neutral-800 border border-yellow-500/30 rounded transition-colors text-[11px]"
            >
              <Download className="w-3.5 h-3.5" />
              <span>Download</span>
            </button>
          </div>
        </div>

        {/* Code Content */}
        <div className="p-4 overflow-x-auto text-neutral-300 leading-relaxed max-h-[580px]">
          <pre className="text-neutral-200">
            <code>{active.code}</code>
          </pre>
        </div>
      </div>
    </div>
  );
};
