/**
 * @license
 * SPDX-License-Identifier: Apache-2.0
 */

import React from 'react';
import { ShieldCheck, Play, Sparkles } from 'lucide-react';
import { Verdict } from '../types/mergeGate';

interface HeaderProps {
  activeTab: 'pipeline' | 'diff' | 'phone' | 'learning' | 'starter-code';
  setActiveTab: (tab: 'pipeline' | 'diff' | 'phone' | 'learning' | 'starter-code') => void;
  onRunEval: () => void;
  isRunning: boolean;
  currentVerdict?: Verdict;
}

export const Header: React.FC<HeaderProps> = ({
  activeTab,
  setActiveTab,
  onRunEval,
  isRunning,
  currentVerdict
}) => {
  return (
    <header className="sticky top-0 z-50 flex items-center justify-between gap-8 px-6 py-3.5 bg-black/95 backdrop-blur-md border-b border-yellow-500/25">
      {/* Zone 1: Single text element wordmark */}
      <div className="flex items-center gap-3 shrink-0">
        <div className="flex items-center justify-center w-8 h-8 rounded-lg bg-yellow-400/15 border border-yellow-400/40 text-yellow-400">
          <ShieldCheck className="w-5 h-5 text-yellow-400" />
        </div>
        <span className="text-lg font-bold tracking-tight text-yellow-400 whitespace-nowrap">
          Merge Gate
        </span>
        <span className="hidden sm:inline-block text-xs font-mono text-neutral-400 border-l border-neutral-800 pl-3">
          AIE Hackathon 2026
        </span>
      </div>

      {/* Zone 2: Navigation Links */}
      <nav className="hidden lg:flex items-center gap-1 text-sm font-medium">
        <button
          onClick={() => setActiveTab('pipeline')}
          className={`px-3 py-1.5 rounded-md transition-colors whitespace-nowrap shrink-0 ${
            activeTab === 'pipeline'
              ? 'bg-yellow-400 text-black font-bold shadow-sm'
              : 'text-neutral-400 hover:text-yellow-300 hover:bg-neutral-900'
          }`}
        >
          Gate Pipeline
        </button>
        <button
          onClick={() => setActiveTab('phone')}
          className={`px-3 py-1.5 rounded-md transition-colors whitespace-nowrap shrink-0 flex items-center gap-1.5 ${
            activeTab === 'phone'
              ? 'bg-yellow-400 text-black font-bold shadow-sm'
              : 'text-neutral-400 hover:text-yellow-300 hover:bg-neutral-900'
          }`}
        >
          iMessage Dispatch
          {currentVerdict === 'BLOCK' && (
            <span className="inline-block w-2 h-2 rounded-full bg-rose-500" />
          )}
        </button>
        <button
          onClick={() => setActiveTab('diff')}
          className={`px-3 py-1.5 rounded-md transition-colors whitespace-nowrap shrink-0 ${
            activeTab === 'diff'
              ? 'bg-yellow-400 text-black font-bold shadow-sm'
              : 'text-neutral-400 hover:text-yellow-300 hover:bg-neutral-900'
          }`}
        >
          Diff & Blame
        </button>
        <button
          onClick={() => setActiveTab('learning')}
          className={`px-3 py-1.5 rounded-md transition-colors whitespace-nowrap shrink-0 ${
            activeTab === 'learning'
              ? 'bg-yellow-400 text-black font-bold shadow-sm'
              : 'text-neutral-400 hover:text-yellow-300 hover:bg-neutral-900'
          }`}
        >
          Learning Track (vN+1)
        </button>
        <button
          onClick={() => setActiveTab('starter-code')}
          className={`px-3 py-1.5 rounded-md transition-colors whitespace-nowrap shrink-0 ${
            activeTab === 'starter-code'
              ? 'bg-yellow-400 text-black font-bold shadow-sm'
              : 'text-neutral-400 hover:text-yellow-300 hover:bg-neutral-900'
          }`}
        >
          Starter Code & CLI
        </button>
      </nav>

      {/* Zone 3: Primary Action Button */}
      <div className="flex items-center gap-3 shrink-0">
        <button
          onClick={onRunEval}
          disabled={isRunning}
          className="flex items-center gap-2 px-4 py-2 text-xs font-bold text-black bg-yellow-400 hover:bg-yellow-300 active:bg-yellow-500 disabled:opacity-50 rounded-lg shadow-sm transition-all whitespace-nowrap shrink-0"
        >
          {isRunning ? (
            <>
              <div className="w-3.5 h-3.5 border-2 border-black/30 border-t-black rounded-full animate-spin" />
              Evaluating...
            </>
          ) : (
            <>
              <Play className="w-3.5 h-3.5 fill-current" />
              Run Gate Check
            </>
          )}
        </button>
      </div>
    </header>
  );
};
