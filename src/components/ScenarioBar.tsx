/**
 * @license
 * SPDX-License-Identifier: Apache-2.0
 */

import React from 'react';
import { Bot, User, GitPullRequest, Sliders } from 'lucide-react';
import { PullRequest } from '../types/mergeGate';

interface ScenarioBarProps {
  scenarios: PullRequest[];
  selectedPr: PullRequest;
  onSelectPr: (pr: PullRequest) => void;
  onOpenCustomModal: () => void;
}

export const ScenarioBar: React.FC<ScenarioBarProps> = ({
  scenarios,
  selectedPr,
  onSelectPr,
  onOpenCustomModal
}) => {
  return (
    <div className="bg-slate-900 border-b border-slate-800 px-6 py-3">
      <div className="flex flex-col md:flex-row items-start md:items-center justify-between gap-4">
        {/* Scenario Switcher Tabs */}
        <div className="flex items-center gap-2 overflow-x-auto w-full md:w-auto pb-1 md:pb-0">
          <span className="text-xs font-medium text-slate-400 whitespace-nowrap mr-2">
            Demo Scenarios:
          </span>
          {scenarios.map(pr => {
            const isSelected = pr.id === selectedPr.id;
            return (
              <button
                key={pr.id}
                onClick={() => onSelectPr(pr)}
                className={`flex items-center gap-2 px-3 py-1.5 text-xs font-medium rounded-md transition-all whitespace-nowrap shrink-0 border ${
                  isSelected
                    ? 'bg-slate-800 text-white border-indigo-500/50 shadow-sm'
                    : 'bg-slate-950/60 text-slate-400 hover:text-slate-200 border-slate-800 hover:border-slate-700'
                }`}
              >
                {pr.authorType === 'agent' ? (
                  <Bot className="w-3.5 h-3.5 text-amber-400" />
                ) : pr.authorType === 'external' ? (
                  <User className="w-3.5 h-3.5 text-purple-400" />
                ) : (
                  <GitPullRequest className="w-3.5 h-3.5 text-emerald-400" />
                )}
                <span className="font-mono font-semibold text-slate-200">#{pr.number}</span>
                <span className="max-w-[140px] truncate text-slate-400">{pr.title}</span>
              </button>
            );
          })}

          <button
            onClick={onOpenCustomModal}
            className="flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium rounded-md bg-slate-950/60 text-slate-400 hover:text-slate-200 border border-dashed border-slate-800 hover:border-slate-700 whitespace-nowrap shrink-0"
          >
            <Sliders className="w-3.5 h-3.5" />
            <span>Custom PR</span>
          </button>
        </div>

        {/* PR Quick Details */}
        <div className="flex items-center gap-3 text-xs text-slate-400 font-mono">
          <span>Author: <strong className="text-slate-200 font-normal">{selectedPr.author}</strong></span>
          <span aria-hidden="true">·</span>
          <span>Repo: <strong className="text-slate-200 font-normal">{selectedPr.repo}</strong></span>
        </div>
      </div>
    </div>
  );
};
