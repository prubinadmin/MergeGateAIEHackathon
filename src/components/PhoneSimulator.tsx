/**
 * @license
 * SPDX-License-Identifier: Apache-2.0
 */

import React, { useState } from 'react';
import {
  Smartphone,
  Send,
  ShieldAlert,
  CheckCircle2,
  Lock,
  ExternalLink,
  ChevronLeft,
  Phone,
  Video,
  Info,
  RotateCcw
} from 'lucide-react';
import { CodeOwner, MergeGateResult, PhoneMessage, PullRequest } from '../types/mergeGate';

interface PhoneSimulatorProps {
  pr: PullRequest;
  owner: CodeOwner;
  gateResult: MergeGateResult | null;
  messages: PhoneMessage[];
  onSendMessage: (text: string) => void;
  onResetMessages: () => void;
  prStatus: string;
}

export const PhoneSimulator: React.FC<PhoneSimulatorProps> = ({
  pr,
  owner,
  gateResult,
  messages,
  onSendMessage,
  onResetMessages,
  prStatus
}) => {
  const [inputText, setInputText] = useState('');

  const handleSend = (e?: React.FormEvent) => {
    if (e) e.preventDefault();
    if (!inputText.trim()) return;
    onSendMessage(inputText.trim());
    setInputText('');
  };

  const handleQuickAction = (cmd: 'BLOCK' | 'WHY' | 'OK' | 'FALSE ALARM') => {
    onSendMessage(cmd);
  };

  return (
    <div className="grid grid-cols-1 lg:grid-cols-12 gap-6 items-start">
      {/* Left Column: Context & Philosophy */}
      <div className="lg:col-span-6 space-y-6">
        <div className="rounded-xl border border-slate-800 bg-slate-900/40 p-5 space-y-4">
          <div className="flex items-center gap-2 text-indigo-400">
            <Smartphone className="w-5 h-5" />
            <h3 className="text-base font-bold text-white tracking-tight">
              iMessage Owner Triage
            </h3>
          </div>
          <p className="text-xs text-slate-300 leading-relaxed">
            In large codebases, AI and external PRs get dumped on whoever is on weekly PR rotation.
            That engineer has never touched this code and rubber-stamps it. Merge Gate uses
            <strong className="text-slate-100 font-semibold"> line-level git blame</strong> to page the engineer who actually wrote
            those lines, directly on their phone with evidence they can verify in 30 seconds.
          </p>

          <div className="border-t border-slate-800 pt-4 space-y-3">
            <h4 className="text-xs font-mono font-semibold text-slate-400 uppercase tracking-wider">
              Core Design Rule: Easy to Stop, Hard to Approve
            </h4>
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-3 text-xs">
              <div className="bg-rose-950/20 border border-rose-900/30 p-3 rounded-lg">
                <div className="font-bold text-rose-300 mb-1 flex items-center gap-1.5">
                  <ShieldAlert className="w-4 h-4 text-rose-400" /> Replying BLOCK
                </div>
                <p className="text-slate-400 text-[11px]">
                  Instantly halts CI/CD, marks PR as blocked, and leaves a blocking status check in GitHub.
                </p>
              </div>
              <div className="bg-slate-950/40 border border-slate-800 p-3 rounded-lg">
                <div className="font-bold text-slate-200 mb-1 flex items-center gap-1.5">
                  <Lock className="w-4 h-4 text-slate-400" /> Replying OK
                </div>
                <p className="text-slate-400 text-[11px]">
                  Never merges. Sends owner to GitHub login where approval requires 2FA & full audit trail.
                </p>
              </div>
            </div>
          </div>

          <div className="bg-slate-950/60 border border-slate-800 p-4 rounded-lg space-y-2 text-xs">
            <div className="flex justify-between items-center text-slate-400">
              <span className="font-mono text-slate-500">Current PR:</span>
              <span className="font-mono text-slate-200 font-semibold">{pr.id} (#{pr.number})</span>
            </div>
            <div className="flex justify-between items-center text-slate-400">
              <span className="font-mono text-slate-500">Recipient Paged:</span>
              <span className="text-slate-200 font-semibold">{owner.name} ({owner.phone || '+1 415-555-0142'})</span>
            </div>
            <div className="flex justify-between items-center text-slate-400">
              <span className="font-mono text-slate-500">PR Merge Status:</span>
              <span className={`font-mono font-bold ${
                prStatus === 'BLOCKED' ? 'text-rose-400' : 'text-emerald-400'
              }`}>
                {prStatus}
              </span>
            </div>
          </div>
        </div>

        {/* Quick Guide to Supported Replies */}
        <div className="rounded-xl border border-slate-800 bg-slate-900/40 p-5 space-y-3">
          <h4 className="text-xs font-mono font-semibold text-slate-400 uppercase tracking-wider">
            Owner Command Reference
          </h4>
          <div className="space-y-2 text-xs font-mono">
            <div className="flex items-start gap-2.5 bg-slate-950/60 p-2.5 rounded border border-slate-800">
              <span className="px-1.5 py-0.5 bg-rose-950 text-rose-300 font-bold rounded shrink-0">BLOCK</span>
              <span className="text-slate-300 font-sans text-xs">
                Immediately blocks PR on GitHub, stopping all merge pipelines.
              </span>
            </div>
            <div className="flex items-start gap-2.5 bg-slate-950/60 p-2.5 rounded border border-slate-800">
              <span className="px-1.5 py-0.5 bg-indigo-950 text-indigo-300 font-bold rounded shrink-0">WHY</span>
              <span className="text-slate-300 font-sans text-xs">
                Returns the exact reproducing test case failure or anti-gaming rule ID and diff context.
              </span>
            </div>
            <div className="flex items-start gap-2.5 bg-slate-950/60 p-2.5 rounded border border-slate-800">
              <span className="px-1.5 py-0.5 bg-slate-800 text-slate-200 font-bold rounded shrink-0">OK</span>
              <span className="text-slate-300 font-sans text-xs">
                Acknowledges without merging. Returns authenticated GitHub review link.
              </span>
            </div>
            <div className="flex items-start gap-2.5 bg-slate-950/60 p-2.5 rounded border border-slate-800">
              <span className="px-1.5 py-0.5 bg-amber-950 text-amber-300 font-bold rounded shrink-0">FALSE ALARM</span>
              <span className="text-slate-300 font-sans text-xs">
                Logs feedback into secondary learning track, triggering Gate vN+1 benchmark.
              </span>
            </div>
          </div>
        </div>
      </div>

      {/* Right Column: High-Fidelity iPhone Device Simulator */}
      <div className="lg:col-span-6 flex justify-center">
        <div className="w-full max-w-[390px] bg-black rounded-[48px] p-3 shadow-2xl border-4 border-slate-800 relative">
          {/* Hardware Frame / Inner Bezel */}
          <div className="bg-slate-950 rounded-[40px] overflow-hidden flex flex-col h-[680px] border border-slate-800/80">
            {/* Top iOS Status Bar */}
            <div className="pt-2 px-6 pb-1 flex items-center justify-between text-[11px] font-semibold text-slate-300 shrink-0">
              <span>11:58</span>
              {/* Dynamic Island Notch */}
              <div className="w-24 h-5 bg-black rounded-full mx-auto" />
              <div className="flex items-center gap-1.5">
                <span>5G</span>
                <div className="w-4 h-2.5 border border-slate-300 rounded-xs flex items-center p-0.5">
                  <div className="w-full h-full bg-slate-300 rounded-2xs" />
                </div>
              </div>
            </div>

            {/* iMessage Header */}
            <div className="px-4 py-2 border-b border-slate-800/80 bg-slate-900/80 backdrop-blur-md flex items-center justify-between shrink-0">
              <div className="flex items-center gap-2">
                <ChevronLeft className="w-5 h-5 text-indigo-400" />
                <div className="w-8 h-8 rounded-full bg-gradient-to-br from-indigo-500 to-indigo-700 flex items-center justify-center font-bold text-xs text-white uppercase shadow-sm">
                  {owner.name.slice(0, 2)}
                </div>
                <div>
                  <div className="text-xs font-semibold text-white leading-tight">
                    {owner.name}
                  </div>
                  <div className="text-[10px] text-slate-400 leading-tight">
                    Merge Gate Bot · iMessage
                  </div>
                </div>
              </div>
              <div className="flex items-center gap-3 text-indigo-400">
                <Phone className="w-4 h-4" />
                <Video className="w-4 h-4" />
              </div>
            </div>

            {/* Chat Scroll Area */}
            <div className="flex-1 overflow-y-auto p-4 space-y-3 text-xs">
              <div className="text-center my-1">
                <span className="text-[10px] text-slate-500 font-mono">
                  Today 11:58 AM · Verified Merge Gate
                </span>
              </div>

              {messages.map((msg) => {
                const isIncoming = msg.sender === 'merge-gate';
                return (
                  <div
                    key={msg.id}
                    className={`flex flex-col ${isIncoming ? 'items-start' : 'items-end'}`}
                  >
                    <div
                      className={`max-w-[85%] rounded-2xl px-3.5 py-2.5 leading-relaxed ${
                        isIncoming
                          ? 'bg-slate-800 text-slate-100 rounded-tl-sm border border-slate-700/60'
                          : 'bg-indigo-600 text-white rounded-tr-sm shadow-sm'
                      }`}
                    >
                      <div className="whitespace-pre-wrap">{msg.body}</div>
                      {msg.evidenceLink && (
                        <div className="mt-2 pt-2 border-t border-slate-700/50">
                          <a
                            href={msg.evidenceLink}
                            target="_blank"
                            rel="noreferrer"
                            className="text-[11px] text-indigo-300 underline flex items-center gap-1"
                          >
                            <span>Inspect Failing Sandbox Run</span>
                            <ExternalLink className="w-3 h-3" />
                          </a>
                        </div>
                      )}
                    </div>
                    <span className="text-[9px] text-slate-500 mt-1 px-1">
                      {msg.timestamp}
                    </span>
                  </div>
                );
              })}
            </div>

            {/* Interactive Action Shortcuts */}
            <div className="px-3 py-2 bg-slate-900/60 border-t border-slate-800/80 shrink-0">
              <div className="text-[10px] text-slate-400 mb-1.5 font-mono flex items-center justify-between">
                <span>TAP QUICK ACTION:</span>
                <button
                  onClick={onResetMessages}
                  className="text-slate-500 hover:text-slate-300 flex items-center gap-1"
                  title="Reset Conversation"
                >
                  <RotateCcw className="w-3 h-3" />
                  <span>Reset</span>
                </button>
              </div>
              <div className="flex flex-wrap gap-1.5">
                <button
                  onClick={() => handleQuickAction('BLOCK')}
                  className="px-2.5 py-1 text-[11px] font-bold rounded-full bg-rose-600/30 hover:bg-rose-600/50 text-rose-300 border border-rose-500/40 transition-colors"
                >
                  BLOCK
                </button>
                <button
                  onClick={() => handleQuickAction('WHY')}
                  className="px-2.5 py-1 text-[11px] font-medium rounded-full bg-slate-800 hover:bg-slate-700 text-slate-200 border border-slate-700 transition-colors"
                >
                  WHY
                </button>
                <button
                  onClick={() => handleQuickAction('OK')}
                  className="px-2.5 py-1 text-[11px] font-medium rounded-full bg-slate-800 hover:bg-slate-700 text-slate-200 border border-slate-700 transition-colors"
                >
                  OK
                </button>
                <button
                  onClick={() => handleQuickAction('FALSE ALARM')}
                  className="px-2.5 py-1 text-[11px] font-medium rounded-full bg-amber-950/50 hover:bg-amber-900/60 text-amber-300 border border-amber-800/40 transition-colors"
                >
                  FALSE ALARM
                </button>
              </div>
            </div>

            {/* iMessage Input Bar */}
            <form
              onSubmit={handleSend}
              className="p-3 bg-slate-900 border-t border-slate-800 flex items-center gap-2 shrink-0"
            >
              <input
                type="text"
                value={inputText}
                onChange={(e) => setInputText(e.target.value)}
                placeholder="iMessage (e.g. BLOCK, WHY)..."
                className="flex-1 bg-slate-950 border border-slate-700 rounded-full px-3.5 py-1.5 text-xs text-white placeholder-slate-500 focus:outline-hidden focus:border-indigo-500"
              />
              <button
                type="submit"
                disabled={!inputText.trim()}
                className="w-7 h-7 rounded-full bg-indigo-600 disabled:opacity-40 text-white flex items-center justify-center shrink-0 hover:bg-indigo-500"
              >
                <Send className="w-3.5 h-3.5" />
              </button>
            </form>
          </div>
        </div>
      </div>
    </div>
  );
};
