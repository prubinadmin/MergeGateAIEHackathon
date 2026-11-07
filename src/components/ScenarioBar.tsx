/**
 * @license
 * SPDX-License-Identifier: Apache-2.0
 */

import React, { useState } from 'react';
import {
  Bot,
  User,
  GitPullRequest,
  Sliders,
  Link2,
  Search,
  Loader2,
  AlertCircle,
  CheckCircle2,
  Sparkles,
  ChevronDown,
  ChevronUp
} from 'lucide-react';
import { PullRequest } from '../types/mergeGate';
import { analyzeGitHubUrl, SAMPLE_GITHUB_LINKS } from '../services/githubAnalyzer';

interface ScenarioBarProps {
  scenarios: PullRequest[];
  selectedPr: PullRequest;
  onSelectPr: (pr: PullRequest) => void;
  onOpenCustomModal: () => void;
  onGitHubPrAnalyzed: (pr: PullRequest) => void;
}

export const ScenarioBar: React.FC<ScenarioBarProps> = ({
  scenarios,
  selectedPr,
  onSelectPr,
  onOpenCustomModal,
  onGitHubPrAnalyzed
}) => {
  const [githubUrl, setGithubUrl] = useState(
    'https://github.com/prubinadmin/MergeGateAIEHackathon/blob/main/test_cases/02_performance_latency_slowdown.py'
  );
  const [isAnalyzing, setIsAnalyzing] = useState(false);
  const [errorMsg, setErrorMsg] = useState<string | null>(null);
  const [lastAnalyzedMsg, setLastAnalyzedMsg] = useState<string | null>(null);
  const [showPresets, setShowPresets] = useState(false);

  const handleAnalyzeUrl = async (urlToAnalyze?: string) => {
    const targetUrl = (urlToAnalyze ?? githubUrl).trim();
    if (!targetUrl) {
      setErrorMsg('Please paste a public GitHub URL (PR, Commit, File, Directory, or Repository).');
      return;
    }

    setIsAnalyzing(true);
    setErrorMsg(null);
    setLastAnalyzedMsg(null);

    try {
      const analyzedPr = await analyzeGitHubUrl(targetUrl);
      onGitHubPrAnalyzed(analyzedPr);
      setLastAnalyzedMsg(`Fetched & analyzed ${analyzedPr.repo} (${analyzedPr.diffSummary})`);
    } catch (err: any) {
      setErrorMsg(err?.message || 'Failed to fetch from GitHub. Ensure the link is a public GitHub URL.');
    } finally {
      setIsAnalyzing(false);
    }
  };

  const handleFormSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    handleAnalyzeUrl();
  };

  return (
    <div className="bg-slate-900 border-b border-slate-800 px-6 py-3 space-y-3">
      {/* Row 1: Live Public GitHub Link Input Bar */}
      <div className="rounded-lg border border-indigo-500/30 bg-slate-950/90 p-3 shadow-inner">
        <form onSubmit={handleFormSubmit} className="flex flex-col lg:flex-row items-stretch lg:items-center gap-2.5">
          <div className="flex items-center gap-2 shrink-0">
            <span className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-md bg-indigo-500/15 border border-indigo-500/30 text-indigo-300 text-xs font-semibold">
              <Link2 className="w-3.5 h-3.5 text-indigo-400" />
              Live GitHub Analyzer
            </span>
          </div>

          <div className="relative flex-1">
            <input
              type="text"
              value={githubUrl}
              onChange={(e) => {
                setGithubUrl(e.target.value);
                if (errorMsg) setErrorMsg(null);
              }}
              placeholder="Paste any public GitHub URL (e.g. https://github.com/owner/repo/pull/12, /commit/sha, or /blob/main/file.py)..."
              className="w-full bg-slate-900 border border-slate-700/80 focus:border-indigo-500 focus:outline-none rounded-md pl-3 pr-3 py-1.5 text-xs font-mono text-slate-100 placeholder:text-slate-500"
            />
          </div>

          <div className="flex items-center gap-2 shrink-0">
            <button
              type="submit"
              disabled={isAnalyzing}
              className="flex items-center justify-center gap-1.5 px-4 py-1.5 rounded-md bg-indigo-600 hover:bg-indigo-500 disabled:opacity-50 text-white text-xs font-semibold transition-all shadow-sm cursor-pointer"
            >
              {isAnalyzing ? (
                <>
                  <Loader2 className="w-3.5 h-3.5 animate-spin" />
                  <span>Fetching GitHub...</span>
                </>
              ) : (
                <>
                  <Search className="w-3.5 h-3.5" />
                  <span>Analyze GitHub Link</span>
                </>
              )}
            </button>

            <button
              type="button"
              onClick={() => setShowPresets(prev => !prev)}
              className="flex items-center gap-1 px-2.5 py-1.5 rounded-md bg-slate-900 hover:bg-slate-800 text-slate-300 border border-slate-700/80 text-xs font-medium transition-colors cursor-pointer"
              title="Toggle sample public GitHub URLs"
            >
              <Sparkles className="w-3.5 h-3.5 text-indigo-400" />
              <span className="hidden sm:inline">Sample Links</span>
              {showPresets ? <ChevronUp className="w-3.5 h-3.5" /> : <ChevronDown className="w-3.5 h-3.5" />}
            </button>
          </div>
        </form>

        {/* Quick Preset Public GitHub Links */}
        {showPresets && (
          <div className="mt-2.5 pt-2.5 border-t border-slate-800/80">
            <div className="text-[11px] text-slate-400 mb-1.5 flex items-center justify-between">
              <span>Click any live public GitHub link below to fetch &amp; run defect analysis:</span>
              <span className="font-mono text-slate-500">Supports PRs · Commits · Files · Directories · Repos</span>
            </div>
            <div className="flex flex-wrap gap-1.5">
              {SAMPLE_GITHUB_LINKS.map((item) => (
                <button
                  key={item.url}
                  type="button"
                  disabled={isAnalyzing}
                  onClick={() => {
                    setGithubUrl(item.url);
                    handleAnalyzeUrl(item.url);
                  }}
                  className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded bg-slate-900 hover:bg-slate-800 border border-slate-800 hover:border-indigo-500/40 text-[11px] text-slate-300 transition-colors cursor-pointer"
                  title={item.description}
                >
                  <span className="px-1.5 py-0.2 rounded bg-indigo-500/15 text-indigo-300 font-mono text-[10px]">
                    {item.badge}
                  </span>
                  <span className="font-mono">{item.label}</span>
                </button>
              ))}
            </div>
          </div>
        )}

        {/* Status / Error Feedback */}
        {errorMsg && (
          <div className="mt-2 flex items-center gap-2 text-xs text-rose-400 bg-rose-950/40 border border-rose-800/50 rounded px-2.5 py-1.5">
            <AlertCircle className="w-3.5 h-3.5 shrink-0" />
            <span>{errorMsg}</span>
          </div>
        )}

        {lastAnalyzedMsg && !errorMsg && (
          <div className="mt-2 flex items-center justify-between gap-2 text-xs text-emerald-300 bg-emerald-950/30 border border-emerald-800/40 rounded px-2.5 py-1">
            <div className="flex items-center gap-1.5">
              <CheckCircle2 className="w-3.5 h-3.5 text-emerald-400 shrink-0" />
              <span>{lastAnalyzedMsg}</span>
            </div>
            <span className="text-[11px] font-mono text-slate-400">
              Inspect findings in Gate Pipeline &amp; Diff Inspector below
            </span>
          </div>
        )}
      </div>

      {/* Row 2: Scenario Switcher Tabs & PR Quick Details */}
      <div className="flex flex-col md:flex-row items-start md:items-center justify-between gap-4">
        <div className="flex items-center gap-2 overflow-x-auto w-full md:w-auto pb-1 md:pb-0">
          <span className="text-xs font-medium text-slate-400 whitespace-nowrap mr-1">
            Scenarios &amp; History:
          </span>
          {scenarios.map(pr => {
            const isSelected = pr.id === selectedPr.id;
            return (
              <button
                key={pr.id}
                onClick={() => onSelectPr(pr)}
                className={`flex items-center gap-2 px-3 py-1.5 text-xs font-medium rounded-md transition-all whitespace-nowrap shrink-0 border cursor-pointer ${
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
                <span className="max-w-[160px] truncate text-slate-400">{pr.title}</span>
              </button>
            );
          })}

          <button
            onClick={onOpenCustomModal}
            className="flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium rounded-md bg-slate-950/60 text-slate-400 hover:text-slate-200 border border-dashed border-slate-800 hover:border-slate-700 whitespace-nowrap shrink-0 cursor-pointer"
          >
            <Sliders className="w-3.5 h-3.5" />
            <span>Custom Diff</span>
          </button>
        </div>

        {/* PR Quick Details */}
        <div className="flex items-center gap-3 text-xs text-slate-400 font-mono shrink-0">
          <span>Author: <strong className="text-slate-200 font-normal">{selectedPr.author}</strong></span>
          <span aria-hidden="true">·</span>
          <span>Repo: <strong className="text-slate-200 font-normal">{selectedPr.repo}</strong></span>
        </div>
      </div>
    </div>
  );
};
