import React from 'react';
import { Check, Code2, FlaskConical, GitMerge, Lock, Scale, ShieldCheck, Smartphone, Users } from 'lucide-react';
import type { StageStatus, Verdict } from './api';

export type NodeKey = 'rules' | 'owners' | 'writer' | 'sandbox' | 'decide' | 'phone' | 'merge';

interface NodeDef {
  key: NodeKey;
  x: number;
  y: number;
  title: string;
  sub: string;
  icon: React.ReactNode;
}

const W = 560;
const H = 624;
const CX = 280;
const CY = 230;

const NODES: NodeDef[] = [
  { key: 'writer', x: 150, y: 85, title: 'Test Writer', sub: 'Muse Spark · sees the spec only', icon: <FlaskConical size={18} /> },
  { key: 'sandbox', x: 410, y: 85, title: 'Sandbox', sub: 'pytest · no secrets · timeout', icon: <ShieldCheck size={18} /> },
  { key: 'rules', x: 70, y: 235, title: 'Rules Engine', sub: 'R1-R9 · plain code', icon: <Code2 size={18} /> },
  { key: 'owners', x: 490, y: 235, title: 'Owner Finder', sub: 'git blame · recency', icon: <Users size={18} /> },
  { key: 'decide', x: CX, y: 380, title: 'decide()', sub: 'Plain code · no AI', icon: <Scale size={18} /> },
  { key: 'phone', x: 470, y: 400, title: "Owner's phone", sub: 'iMessage · BLOCK, never approve', icon: <Smartphone size={18} /> },
  { key: 'merge', x: CX, y: 500, title: 'GitHub merge', sub: 'Only decide() can reach it', icon: <GitMerge size={18} /> },
];

const tone = (s: StageStatus) =>
  s === 'start'
    ? 'border-amber-400 text-amber-300 shadow-[0_0_24px_rgba(245,165,36,0.45)] animate-pulse'
    : s === 'done'
      ? 'border-amber-500/70 text-amber-300'
      : s === 'skipped'
        ? 'border-zinc-700 text-zinc-600 border-dashed'
        : 'border-zinc-700 text-zinc-500';

export function AgentGraph({
  states,
  verdict,
  running,
}: {
  states: Record<NodeKey, StageStatus>;
  verdict: Verdict | null;
  running: boolean;
}) {
  const mergeTone =
    verdict === 'BLOCK'
      ? 'border-red-500 text-red-400 bg-red-500/10 shadow-[0_0_24px_rgba(239,68,68,0.35)]'
      : verdict === 'PASS'
        ? 'border-emerald-500 text-emerald-400 bg-emerald-500/10'
        : verdict === 'REVIEW'
          ? 'border-sky-500 text-sky-400 bg-sky-500/10'
          : 'border-zinc-700 text-zinc-500';
  const mergeTag =
    verdict === 'BLOCK' ? 'merge blocked' : verdict === 'PASS' ? 'merge allowed' : verdict === 'REVIEW' ? 'waiting for owner' : 'sealed';

  const lineOn = (k: NodeKey) => states[k] === 'start' || states[k] === 'done';

  return (
    <div className="relative mx-auto" style={{ width: W, height: H }}>
      <div
        className="absolute rounded-full pointer-events-none"
        style={{
          left: CX - 170, top: CY - 170, width: 340, height: 340,
          background: running ? 'radial-gradient(circle, rgba(245,165,36,0.16), transparent 70%)' : 'radial-gradient(circle, rgba(245,165,36,0.07), transparent 70%)',
        }}
      />
      <svg className="absolute inset-0" width={W} height={H}>
        <circle cx={CX} cy={CY} r={205} fill="none" stroke="rgba(255,255,255,0.05)" strokeDasharray="2 6" />
        {NODES.filter((n) => n.key !== 'merge').map((n) => (
          <line key={n.key} x1={CX} y1={CY} x2={n.x} y2={n.y}
            stroke={lineOn(n.key) ? 'rgba(245,165,36,0.55)' : 'rgba(255,255,255,0.09)'}
            strokeWidth={1.2} strokeDasharray="3 5" />
        ))}
        <line x1={CX} y1={380} x2={CX} y2={500}
          stroke={verdict === 'BLOCK' ? 'rgba(239,68,68,0.6)' : verdict ? 'rgba(52,211,153,0.6)' : 'rgba(255,255,255,0.09)'}
          strokeWidth={1.2} strokeDasharray="3 5" />
      </svg>

      <div className="absolute flex flex-col items-center text-center" style={{ left: CX - 70, top: CY - 34, width: 140 }}>
        <div className={`w-[60px] h-[60px] rounded-full border-2 flex items-center justify-center bg-zinc-950 ${running ? 'border-amber-400 text-amber-300' : 'border-amber-600/60 text-amber-400'}`}>
          <Lock size={22} />
        </div>
        <div className="mt-2 text-[14px] font-semibold text-zinc-100">Merge Gate</div>
        <div className="text-[11px] font-mono text-zinc-500 leading-tight">runs the case</div>
      </div>

      {NODES.map((n) => {
        const isMerge = n.key === 'merge';
        const s = states[n.key];
        return (
          <div key={n.key} className="absolute flex flex-col items-center text-center" style={{ left: n.x - 75, top: n.y - 24, width: 150 }}>
            <div className={`relative w-12 h-12 rounded-full border-2 flex items-center justify-center bg-zinc-950 transition-all ${isMerge ? mergeTone : tone(s)}`}>
              {n.icon}
              {!isMerge && s === 'done' && (
                <span className="absolute -top-1 -right-1 w-5 h-5 rounded-full bg-amber-500 text-zinc-950 flex items-center justify-center">
                  <Check size={13} strokeWidth={3} />
                </span>
              )}
            </div>
            <div className={`mt-1.5 text-[13px] font-semibold ${s === 'idle' && !isMerge ? 'text-zinc-400' : 'text-zinc-100'}`}>{n.title}</div>
            <div className="text-[10.5px] font-mono text-zinc-500 leading-tight">{n.sub}</div>
            {isMerge && (
              <span className={`mt-1.5 px-2 py-0.5 rounded border text-[10.5px] font-mono ${mergeTone}`}>{mergeTag}</span>
            )}
          </div>
        );
      })}
    </div>
  );
}
