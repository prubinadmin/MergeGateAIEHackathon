import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { ChevronRight, CircleCheck, GitPullRequest, Hash, Loader2, Lock, Play, Send, ShieldCheck, Smartphone } from 'lucide-react';
import { BorderBeam } from '../components/ui/border-beam';
import { AgentGraph, NodeKey } from './AgentGraph';
import {
  API_BASE, DemoPr, Evidence, Report, RULE_LABEL, RULES, RunEvent, StageEvent, StageStatus, Stats,
  getDemo, getHealth, getMessage, getStats, pageOwner, postReply, runGate,
} from './api';

interface Bubble { from: 'gate' | 'owner'; text: string; at: string }

interface CaseState {
  stages: Partial<Record<string, StageEvent>>;
  report: Report | null;
  error: string;
  clock: number;
  chainOk: boolean | null;
  bubbles: Bubble[];
  ownerBlocked: boolean;
  startedAt: number;
}

const EMPTY: CaseState = { stages: {}, report: null, error: '', clock: 0, chainOk: null, bubbles: [], ownerBlocked: false, startedAt: 0 };
const now = () => new Date().toLocaleTimeString([], { hour: 'numeric', minute: '2-digit', second: '2-digit' });

function nodeStates(c: CaseState): Record<NodeKey, StageStatus> {
  const st = (name: string): StageStatus => (c.stages[name]?.status as StageStatus) || 'idle';
  return {
    rules: st('rules'),
    owners: st('owners'),
    writer: st('testgen'),
    sandbox: st('testgen'),
    decide: st('decide'),
    phone: c.bubbles.length ? 'done' : st('summary') === 'start' ? 'start' : 'idle',
    merge: c.report ? 'done' : 'idle',
  };
}

const verdictColor = (v?: string) =>
  v === 'BLOCK' ? 'text-red-400 border-red-500/70 bg-red-500/10'
    : v === 'PASS' ? 'text-emerald-400 border-emerald-500/70 bg-emerald-500/10'
      : v === 'REVIEW' ? 'text-sky-400 border-sky-500/70 bg-sky-500/10'
        : 'text-zinc-500 border-zinc-700';

const sevChip = (e: Evidence) =>
  e.severity === 'block' ? 'bg-red-500/15 text-red-300 border-red-500/40' : 'bg-sky-500/15 text-sky-300 border-sky-500/40';

function StatsBar({ stats, llm }: { stats: Stats | null; llm: boolean | null }) {
  const n = (v: number | undefined | null) => (v === undefined || v === null ? '–' : v);
  return (
    <div className="mx-6 mt-4 rounded-xl border border-zinc-800 bg-zinc-900/40 px-5 py-3 flex flex-wrap items-center gap-x-7 gap-y-2 text-[13px] tabular-nums">
      <span className="flex items-center gap-2 font-mono text-[12px] text-amber-400"><span className="w-1.5 h-1.5 rounded-full bg-amber-400 animate-pulse" />LIVE</span>
      <span><b className="text-lg text-zinc-100 mr-1.5">{n(stats?.checked)}</b><span className="text-zinc-400">PRs checked</span></span>
      <span><b className="text-lg text-red-400 mr-1.5">{n(stats?.blocked)}</b><span className="text-zinc-400">blocked</span></span>
      <span><b className="text-lg text-zinc-100 mr-1.5">{n(stats?.owner_blocks)}</b><span className="text-zinc-400">blocked from a phone</span></span>
      <span><b className="text-lg text-emerald-400 mr-1.5">0</b><span className="text-zinc-400">approved by text, ever</span></span>
      <span><b className="text-lg text-zinc-100 mr-1.5">{stats?.median_ms ? `${(stats.median_ms / 1000).toFixed(1)}s` : '–'}</b><span className="text-zinc-400">median decision</span></span>
      <span className="ml-auto flex items-center gap-4 font-mono text-[11.5px] tracking-wide">
        <span className={llm ? 'text-amber-300' : 'text-zinc-500'}>MUSE SPARK {llm === null ? '…' : llm ? 'ON' : 'OFF'}</span>
        <span className={stats?.chain_ok === false ? 'text-red-400' : 'text-emerald-400'}>
          {stats?.chain_ok === false ? '✗ AUDIT CHAIN BROKEN' : '✓ AUDIT CHAIN VERIFIED'}
          <span className="text-zinc-500"> · {n(stats?.events)} EVENTS</span>
        </span>
      </span>
    </div>
  );
}

function Lane({ title, ev, children }: { title: string; ev?: StageEvent; children?: React.ReactNode }) {
  const status = ev?.status;
  return (
    <div className={`rounded-xl border px-4 py-3 ${status === 'start' ? 'border-amber-500/60 bg-amber-500/5' : 'border-zinc-800 bg-zinc-900/40'}`}>
      <div className="flex items-center justify-between font-mono text-[11.5px] tracking-wider">
        <span className="text-amber-400">{title}</span>
        <span className="text-zinc-500">
          {status === 'done' ? <span className="text-zinc-300">✓ DONE · {((ev?.ms || 0) / 1000).toFixed(1)}s</span>
            : status === 'start' ? <span className="text-amber-300 animate-pulse">RUNNING…</span>
              : status === 'skipped' ? 'SKIPPED' : 'WAITING'}
        </span>
      </div>
      {children && <div className="mt-2 text-[13px] text-zinc-200">{children}</div>}
    </div>
  );
}

function Phone({ owner, c, onReply, busy }: { owner?: string; c: CaseState; onReply: (t: string) => void; busy: boolean }) {
  const box = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const el = box.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [c.bubbles.length]);
  const canReply = !!c.report && c.report.verdict !== 'PASS' && !busy;
  return (
    <div className="mx-auto w-[300px] rounded-[38px] border-[6px] border-zinc-800 bg-black p-3 shadow-2xl">
      <div className="mx-auto mb-2 h-5 w-24 rounded-full bg-zinc-900" />
      <div className="text-center text-[11px] text-zinc-500">iMessage</div>
      <div className="text-center text-[13px] font-semibold text-zinc-100">Merge Gate → {owner || 'code owner'}</div>
      <div ref={box} className="mt-3 h-[360px] overflow-y-auto space-y-2 px-1">
        {!c.bubbles.length && <div className="pt-24 text-center text-[12px] text-zinc-600">The owner's phone is quiet until the gate decides.</div>}
        {c.bubbles.map((b, i) => (
          <div key={i} className={`flex ${b.from === 'owner' ? 'justify-end' : 'justify-start'}`}>
            <div className={`max-w-[85%] whitespace-pre-wrap break-words [overflow-wrap:anywhere] rounded-2xl px-3 py-2 text-[12.5px] leading-snug ${b.from === 'owner' ? 'bg-blue-600 text-white rounded-br-md' : 'bg-zinc-800 text-zinc-100 rounded-bl-md'}`}>
              {b.text}
              <div className="mt-1 text-[9.5px] opacity-50">{b.at}</div>
            </div>
          </div>
        ))}
      </div>
      <div className="mt-2 grid grid-cols-4 gap-1.5">
        {['BLOCK', 'WHY', 'OK', 'FALSE ALARM'].map((t) => (
          <button key={t} disabled={!canReply} onClick={() => onReply(t)}
            className={`rounded-lg py-1.5 text-[10.5px] font-semibold transition disabled:opacity-30 ${t === 'BLOCK' ? 'bg-red-600 hover:bg-red-500 text-white' : 'bg-zinc-800 hover:bg-zinc-700 text-zinc-200'}`}>
            {t}
          </button>
        ))}
      </div>
      <div className="mt-2 text-center text-[10px] text-zinc-600">A text can block a merge. It can never approve one.</div>
    </div>
  );
}

export default function WarRoom() {
  const [prs, setPrs] = useState<DemoPr[]>([]);
  const [sel, setSel] = useState<string>('');
  const [cases, setCases] = useState<Record<string, CaseState>>({});
  const [running, setRunning] = useState<string>('');
  const [stats, setStats] = useState<Stats | null>(null);
  const [llm, setLlm] = useState<boolean | null>(null);
  const [useLlm, setUseLlm] = useState<boolean>(true);
  const [apiDown, setApiDown] = useState('');
  const [showDiff, setShowDiff] = useState(false);
  const [showWhy, setShowWhy] = useState(true);
  const [replyBusy, setReplyBusy] = useState(false);
  const [paging, setPaging] = useState<Record<string, { status: 'sending' | 'sent' | 'error'; note: string }>>({});

  // the case clock must keep moving during long stages (Muse Spark can take a minute), or the demo looks frozen
  const [, setTick] = useState(0);
  useEffect(() => {
    if (!running) return;
    const t = setInterval(() => setTick((x) => x + 1), 100);
    return () => clearInterval(t);
  }, [running]);

  const refreshStats = useCallback(() => getStats().then(setStats).catch(() => {}), []);

  useEffect(() => {
    getHealth()
      .then((h) => { setLlm(h.llm); setUseLlm(h.llm); return getDemo(); })
      .then((d) => { setPrs(d); setSel(d[0]?.pr_id || ''); })
      .catch(() => setApiDown(`Cannot reach the Merge Gate API at ${API_BASE}. Start it with: python -m merge_gate serve`));
    refreshStats();
  }, [refreshStats]);

  const patch = (id: string, f: (c: CaseState) => CaseState) =>
    setCases((all) => ({ ...all, [id]: f(all[id] || EMPTY) }));

  const run = useCallback((id: string) => {
    if (running) return;
    setSel(id);
    setRunning(id);
    setCases((all) => ({ ...all, [id]: { ...EMPTY, startedAt: Date.now() } }));
    runGate(id, useLlm, (ev: RunEvent) => {
      if (ev.type === 'stage') patch(id, (c) => ({ ...c, clock: ev.t, stages: { ...c.stages, [ev.stage]: ev } }));
      else if (ev.type === 'report') {
        patch(id, (c) => ({ ...c, clock: ev.t, report: ev.report, chainOk: ev.chain_ok }));
        setRunning('');
        refreshStats();
        getMessage(id).then((m) => patch(id, (c) => ({ ...c, bubbles: [{ from: 'gate', text: m.text, at: now() }] })));
      } else if (ev.type === 'error') {
        patch(id, (c) => ({ ...c, error: ev.error }));
        setRunning('');
      }
    });
  }, [running, useLlm, refreshStats]);

  const reply = async (text: string) => {
    const id = sel;
    setReplyBusy(true);
    patch(id, (c) => ({ ...c, bubbles: [...c.bubbles, { from: 'owner', text, at: now() }] }));
    try {
      const r = await postReply(id, text);
      patch(id, (c) => ({
        ...c,
        ownerBlocked: c.ownerBlocked || r.action === 'block_pr',
        bubbles: [...c.bubbles, { from: 'gate', text: r.text, at: now() }],
      }));
      refreshStats();
    } finally {
      setReplyBusy(false);
    }
  };

  const page = async (id: string) => {
    setPaging((all) => ({ ...all, [id]: { status: 'sending', note: '' } }));
    try {
      const m = await pageOwner(id);
      const real = m.sent && !m.sent.startsWith('console-');
      setPaging((all) => ({ ...all, [id]: { status: 'sent', note: real ? `Delivered to Sendblue for ${m.to?.name}` : `No Sendblue keys on the server: printed to its console instead` } }));
    } catch (e) {
      setPaging((all) => ({ ...all, [id]: { status: 'error', note: (e as Error).message } }));
    }
  };

  const pr = prs.find((p) => p.pr_id === sel);
  const c = cases[sel] || EMPTY;
  const r = c.report;
  const fired = useMemo(() => {
    const m: Record<string, 'block' | 'review'> = {};
    (r?.evidence || c.stages.rules?.evidence || []).forEach((e: Evidence) => {
      if (e.type === 'rule') m[e.id] = m[e.id] === 'block' ? 'block' : e.severity;
    });
    return m;
  }, [r, c.stages.rules]);
  const tg = c.stages.testgen;
  const clock = running === sel && c.startedAt ? Math.max(c.clock, (Date.now() - c.startedAt) / 1000) : c.clock;
  const owners = (c.stages.owners?.owners || r?.owners || []) as Report['owners'];

  return (
    <div className="min-h-screen bg-[#0a0a0b] text-zinc-100">
      {apiDown && <div className="bg-red-950/60 border-b border-red-900 px-6 py-2 text-[13px] text-red-200 font-mono">{apiDown}</div>}
      <StatsBar stats={stats} llm={llm} />

      <div className="mx-6 mt-3 rounded-xl border border-zinc-800 bg-zinc-950">
        <div className="flex flex-wrap items-center gap-2 border-b border-zinc-800 px-4 py-3">
          {prs.map((p) => {
            const v = cases[p.pr_id]?.report?.verdict;
            return (
              <button key={p.pr_id} onClick={() => setSel(p.pr_id)}
                className={`flex items-center gap-2 rounded-lg border px-3 py-1.5 text-[13px] transition ${sel === p.pr_id ? 'border-amber-600/60 bg-amber-500/10 text-zinc-100' : 'border-transparent text-zinc-400 hover:text-zinc-200'}`}>
                <GitPullRequest size={14} />
                <span className="font-mono text-[11.5px] text-zinc-500">{p.pr_id}</span>
                {p.title}
                <span className={`w-2 h-2 rounded-full ${v === 'BLOCK' ? 'bg-red-500' : v === 'PASS' ? 'bg-emerald-500' : v === 'REVIEW' ? 'bg-sky-500' : 'bg-zinc-700'}`} />
              </button>
            );
          })}
          <div className="ml-auto flex items-center gap-4">
            <label className="flex items-center gap-2 text-[12px] text-zinc-400 font-mono">
              <input type="checkbox" checked={useLlm} disabled={!llm} onChange={(e) => setUseLlm(e.target.checked)} className="accent-amber-500" />
              Muse Spark tests
            </label>
            <div className="text-right">
              <div className="font-mono text-[10.5px] tracking-wider text-zinc-500">CASE CLOCK · REAL TIME</div>
              <div className="font-mono text-lg text-zinc-100 tabular-nums">T+{clock.toFixed(1)}s</div>
            </div>
          </div>
        </div>

        <div className="grid grid-cols-1 lg:grid-cols-[560px_minmax(0,1fr)] xl:grid-cols-[560px_minmax(0,1fr)_312px] gap-5 p-5">
          <div className="min-w-0">
            <div className="overflow-x-auto">
              <AgentGraph states={nodeStates(c)} verdict={r?.verdict || null} running={running === sel} />
            </div>
            <div className="mt-4 flex items-center gap-2 text-[14px] text-zinc-300">
              <span className={`w-2 h-2 rounded-full ${r ? (r.verdict === 'BLOCK' ? 'bg-red-500' : r.verdict === 'PASS' ? 'bg-emerald-500' : 'bg-sky-500') : 'bg-zinc-600'}`} />
              {!r && running !== sel && 'Pick a PR and run the gate.'}
              {running === sel && 'Running the real gate on this PR…'}
              {r?.verdict === 'BLOCK' && `BLOCK. The merge button was never reachable${c.ownerBlocked ? '; the owner confirmed from their phone' : ''}.`}
              {r?.verdict === 'REVIEW' && 'REVIEW. The merge waits for the code owner.'}
              {r?.verdict === 'PASS' && 'PASS. Nothing found; the owner gets an FYI.'}
            </div>
          </div>

          <div className="space-y-3 min-w-0">
            {pr && (
              <div className="rounded-xl border border-zinc-800 bg-zinc-900/40 px-4 py-3">
                <div className="font-mono text-[11.5px] tracking-wider text-zinc-500">PULL REQUEST · {pr.pr_id} · OPENED BY {pr.opened_by.toUpperCase()}</div>
                <div className="mt-1 text-[16px] font-semibold">{pr.title}</div>
                <div className="mt-1 text-[13.5px] text-zinc-300">Issue: {pr.issue_text}</div>
                <div className="mt-2 flex flex-wrap gap-1.5">
                  {pr.files.map((f) => <span key={f} className="rounded border border-zinc-700 px-2 py-0.5 font-mono text-[11.5px] text-zinc-300">{f}</span>)}
                </div>
                <div className="mt-3 flex items-center gap-3">
                  <button onClick={() => run(pr.pr_id)} disabled={!!running}
                    className="flex items-center gap-2 rounded-lg bg-amber-500 px-4 py-1.5 text-[13px] font-semibold text-zinc-950 hover:bg-amber-400 disabled:opacity-40">
                    <Play size={14} /> {running === pr.pr_id ? 'Running…' : r ? 'Run again' : 'Run the gate'}
                  </button>
                  <button onClick={() => setShowDiff((s) => !s)} className="text-[12.5px] text-zinc-400 hover:text-zinc-200">{showDiff ? 'Hide diff' : 'View diff'}</button>
                </div>
                {showDiff && (
                  <pre className="mt-3 max-h-72 overflow-auto rounded-lg bg-black/60 p-3 text-[11.5px] leading-relaxed">
                    {pr.diff.split('\n').map((l, i) => (
                      <div key={i} className={l.startsWith('+') && !l.startsWith('+++') ? 'text-emerald-300' : l.startsWith('-') && !l.startsWith('---') ? 'text-red-300' : l.startsWith('@@') ? 'text-sky-400' : 'text-zinc-500'}>{l || ' '}</div>
                    ))}
                  </pre>
                )}
              </div>
            )}

            {c.error && <div className="rounded-xl border border-red-900 bg-red-950/40 px-4 py-3 text-[13px] text-red-200 font-mono">{c.error}</div>}

            <div className={`relative overflow-hidden rounded-xl border px-4 py-4 transition-colors duration-200 ${r ? verdictColor(r.verdict).replace(/text-\S+/, '') : 'border-zinc-800'} bg-zinc-900/30`}>
              {running === sel && <BorderBeam size={120} duration={4} colorFrom="#f59e0b" colorTo="#fde68a" />}
              <div className="flex items-center gap-4">
                <span className={`rounded-lg border-2 px-4 py-1 font-mono text-4xl font-bold tracking-[0.2em] ${verdictColor(r?.verdict)}`}>{r?.verdict || '—'}</span>
                <div className="text-[13.5px] text-zinc-300">
                  {r ? (r.verdict === 'PASS' ? 'Every check passed.' : `${r.evidence.length} piece${r.evidence.length === 1 ? '' : 's'} of evidence. Sent to ${r.owners[0]?.name || 'the code owner'}.`) : 'No verdict yet.'}
                  {r && <div className="mt-0.5 font-mono text-[11px] text-zinc-500">gate {r.gate_version} · decided by decide(), plain code, no AI</div>}
                </div>
              </div>
              {r && r.evidence.length > 0 && (
                <div className="mt-3 flex flex-wrap gap-1.5">
                  {r.evidence.map((e, i) => (
                    <span key={i} className={`rounded border px-2 py-0.5 text-[12px] ${sevChip(e)}`}>
                      <b className="font-mono">{e.type === 'rule' ? e.id.split('_')[0] : 'TEST'}</b> {e.type === 'rule' ? RULE_LABEL[e.id] || e.id : e.id.replace('gate::', '')}
                    </span>
                  ))}
                </div>
              )}
              <div className="mt-3 grid grid-cols-9 gap-1.5">
                {RULES.map((rule) => (
                  <div key={rule.id} title={RULE_LABEL[rule.id]}
                    className={`rounded py-1 text-center font-mono text-[12px] border ${fired[rule.id] === 'block' ? 'bg-red-500 text-white border-red-400' : fired[rule.id] === 'review' ? 'bg-sky-600/80 text-white border-sky-400' : 'border-zinc-800 text-zinc-500'}`}>
                    {rule.short}
                  </div>
                ))}
              </div>
              {r && r.evidence.length > 0 && (
                <div className="mt-3">
                  <button onClick={() => setShowWhy((s) => !s)} className="flex items-center gap-1 font-mono text-[11.5px] tracking-wider text-zinc-400 hover:text-zinc-200">
                    <ChevronRight size={13} className={showWhy ? 'rotate-90' : ''} /> WHY, IN THE GATE'S WORDS
                  </button>
                  {showWhy && (
                    <ul className="mt-2 space-y-1.5">
                      {r.evidence.map((e, i) => (
                        <li key={i} className="text-[13px] text-zinc-200">
                          <span className={`mr-2 rounded border px-1.5 font-mono text-[10.5px] ${sevChip(e)}`}>{e.severity}</span>
                          {e.detail}
                          {e.file && <span className="ml-1 font-mono text-[11.5px] text-zinc-500">{e.file}{e.line ? `:${e.line}` : ''}</span>}
                        </li>
                      ))}
                    </ul>
                  )}
                </div>
              )}
            </div>

            <Lane title="RULES ENGINE" ev={c.stages.rules}>
              {c.stages.rules?.status === 'done' && (
                (c.stages.rules.evidence || []).length
                  ? <span>{c.stages.rules.evidence.length} rule{c.stages.rules.evidence.length === 1 ? '' : 's'} fired: {c.stages.rules.evidence.map((e: Evidence) => e.id.split('_')[0]).join(', ')}</span>
                  : <span className="text-zinc-400">No rule fired.</span>
              )}
            </Lane>

            <Lane title="OWNER FINDER" ev={c.stages.owners}>
              {owners.length > 0 && (
                <div className="space-y-1.5">
                  {owners.slice(0, 3).map((o, i) => (
                    <div key={o.email} className="flex items-center gap-3">
                      <span className={`w-20 shrink-0 truncate ${i === 0 ? 'font-semibold text-zinc-100' : 'text-zinc-400'}`}>{o.name}</span>
                      <div className="h-1.5 flex-1 rounded bg-zinc-800"><div className="h-1.5 rounded bg-amber-500" style={{ width: `${Math.round(o.score * 100)}%` }} /></div>
                      <span className="w-12 text-right font-mono text-[11.5px] text-zinc-300">{Math.round(o.score * 100)}%</span>
                      <span className="w-36 text-right font-mono text-[11.5px] text-zinc-500">{o.lines} lines · {o.last_touched}</span>
                      {i === 0 && <span className="rounded bg-amber-500/15 px-1.5 text-[10.5px] text-amber-300">gets the text</span>}
                    </div>
                  ))}
                </div>
              )}
            </Lane>

            <Lane title="TEST WRITER (MUSE SPARK) + SANDBOX" ev={tg}>
              {tg?.status === 'skipped' && <span className="text-zinc-500">Skipped: {tg.reason}. Rules and ownership still ran.</span>}
              {tg?.status === 'start' && <span className="text-zinc-400">Writing tests from the issue and the public interface only, then running them on base and on the PR…</span>}
              {tg?.status === 'done' && (
                tg.error ? <span className="text-amber-300">{tg.error}</span> : (
                  <div className="space-y-1.5">
                    <div className="flex flex-wrap gap-1.5 text-[12px]">
                      <span className="rounded border border-zinc-700 px-2 py-0.5">{tg.kept?.length || 0} invariant tests kept</span>
                      <span className="rounded border border-zinc-700 px-2 py-0.5">{tg.dropped?.length || 0} dropped (failed on base)</span>
                      {tg.base && <span className="rounded border border-zinc-700 px-2 py-0.5 font-mono">base {tg.base.passed} pass / {tg.base.failed} fail</span>}
                      {tg.head && <span className={`rounded border px-2 py-0.5 font-mono ${tg.head.failed ? 'border-red-500/50 text-red-300' : 'border-zinc-700'}`}>PR {tg.head.passed} pass / {tg.head.failed} fail</span>}
                    </div>
                    {(tg.evidence || []).map((e: Evidence, i: number) => (
                      <div key={i} className="text-[12.5px]"><span className={`mr-2 rounded border px-1.5 font-mono text-[10.5px] ${sevChip(e)}`}>{e.severity}</span>{e.detail}</div>
                    ))}
                    {tg.source && (
                      <details className="text-[12px]"><summary className="cursor-pointer text-zinc-400">Tests Muse Spark wrote (it never saw the PR)</summary>
                        <pre className="mt-2 max-h-64 overflow-auto rounded bg-black/60 p-3 text-[11px] text-zinc-300">{tg.source}</pre>
                      </details>
                    )}
                  </div>
                )
              )}
            </Lane>

            <Lane title="DECIDE() · PLAIN CODE" ev={c.stages.decide}>
              {c.stages.decide && <span>Verdict <b>{c.stages.decide.verdict}</b> from {r?.evidence.length ?? '…'} evidence items · gate {c.stages.decide.gate_version}</span>}
            </Lane>

            <Lane title="MESSAGE TO THE OWNER" ev={c.stages.summary}>
              {c.stages.summary?.summary && <span>“{c.stages.summary.summary}”</span>}
            </Lane>

            {r && (
              <div className="flex flex-wrap items-center gap-x-5 gap-y-1 px-1 font-mono text-[11px] text-zinc-500">
                <span className="flex items-center gap-1"><Hash size={12} />{r.run_hash.slice(0, 23)}…</span>
                <span className={c.chainOk ? 'text-emerald-400' : 'text-red-400'}>{c.chainOk ? '✓ logged to the audit chain' : '✗ audit chain broken'}</span>
              </div>
            )}
          </div>

          <div className="lg:col-span-2 xl:col-span-1">
            <Phone owner={r?.owners[0]?.name} c={c} onReply={reply} busy={replyBusy} />
            <div className="mx-auto mt-3 w-[300px]">
              <button onClick={() => page(sel)} disabled={!r || r.verdict === 'PASS' || paging[sel]?.status === 'sending'}
                className="flex w-full items-center justify-center gap-2 rounded-lg border border-amber-500/50 bg-amber-500/10 py-2 text-[13px] font-semibold text-amber-200 transition-colors duration-150 hover:bg-amber-500/20 focus-visible:outline focus-visible:outline-2 focus-visible:outline-amber-400 disabled:cursor-not-allowed disabled:opacity-35">
                {paging[sel]?.status === 'sending' ? <Loader2 size={14} className="animate-spin" /> : <Send size={14} />}
                {paging[sel]?.status === 'sending' ? 'Paging…' : `Page ${r?.owners[0]?.name || 'the owner'}'s real phone`}
              </button>
              {paging[sel] && paging[sel].status !== 'sending' && (
                <div role="status" className={`mt-2 flex items-start gap-1.5 text-[12px] ${paging[sel].status === 'sent' ? 'text-emerald-300' : 'text-red-300'}`}>
                  {paging[sel].status === 'sent' ? <Smartphone size={13} className="mt-0.5 shrink-0" /> : <Lock size={13} className="mt-0.5 shrink-0" />}
                  {paging[sel].note}
                </div>
              )}
              {!r && <div className="mt-2 text-[11.5px] text-zinc-500">Run the gate first; only a BLOCK or REVIEW pages the owner.</div>}
            </div>
            {c.ownerBlocked && (
              <div className="mx-auto mt-3 w-[300px] rounded-lg border border-red-500/50 bg-red-500/10 px-3 py-2 text-[12px] text-red-200 flex items-center gap-2">
                <Lock size={14} /> merge-gate check: failure · blocked by {r?.owners[0]?.name} from their phone
              </div>
            )}
          </div>
        </div>
      </div>
      <div className="px-6 py-4 font-mono text-[11px] text-zinc-600 flex items-center gap-2">
        <ShieldCheck size={12} /> Every lane above is a real stage of `python -m merge_gate` streamed from {API_BASE}. Nothing on this page is simulated.
      </div>
    </div>
  );
}
