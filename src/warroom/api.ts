// Client for the real Merge Gate API (`python -m merge_gate serve`). Nothing here simulates a result:
// without a backend it replays a real recorded run and says so.
import recorded from './recorded-run.json';

export const API_BASE: string =
  (import.meta as any).env?.VITE_MERGE_GATE_API || 'http://127.0.0.1:8787';

export type Verdict = 'BLOCK' | 'REVIEW' | 'PASS';

export interface Evidence {
  type: 'failing_test' | 'rule';
  id: string;
  detail: string;
  file?: string | null;
  line?: number | null;
  severity: 'block' | 'review';
}

export interface Owner {
  name: string;
  email: string;
  lines: number;
  last_touched: string;
  score: number;
}

export interface Report {
  pr_id: string;
  verdict: Verdict;
  evidence: Evidence[];
  owners: Owner[];
  summary: string;
  run_hash: string;
  gate_version: string;
}

export interface DemoPr {
  pr_id: string;
  title: string;
  issue_text: string;
  opened_by: string;
  files: string[];
  diff: string;
}

export interface Stats {
  checked: number;
  blocked: number;
  review: number;
  passed: number;
  owner_replies: number;
  owner_blocks: number;
  median_ms: number | null;
  events: number;
  chain_ok: boolean;
  llm: boolean;
}

export type StageName = 'rules' | 'owners' | 'testgen' | 'decide' | 'summary';
export type StageStatus = 'idle' | 'start' | 'done' | 'skipped';

export interface StageEvent {
  type: 'stage';
  stage: StageName;
  status: 'start' | 'done' | 'skipped';
  t: number;
  ms?: number;
  [k: string]: any;
}

export type RunEvent =
  | { type: 'begin'; pr_id: string; llm: boolean; t: number }
  | StageEvent
  | { type: 'report'; report: Report; chain_ok: boolean; t: number }
  | { type: 'error'; error: string; t: number };

async function j<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(API_BASE + path, {
    ...init,
    headers: { 'Content-Type': 'application/json', ...(init?.headers || {}) },
  });
  const body = await res.json();
  if (!res.ok) throw new Error(body?.error || `HTTP ${res.status}`);
  return body as T;
}

// Without a reachable gate (e.g. the public site), replay a real recorded run instead of an empty error.
// Captured from `python -m merge_gate serve` with curl into recorded-run.json.
interface Recording {
  recorded_at: string;
  health: { ok: boolean; llm: boolean };
  demo: DemoPr[];
  stats: Stats;
  runs: Record<string, RunEvent[]>;
  messages: Record<string, { to: Owner | null; text: string }>;
}
const REC = recorded as unknown as Recording;
export const RECORDED_AT = REC.recorded_at;
const REPLAY_SECONDS = 8;

let replay = false;
/** True once the health probe failed and the page is replaying recorded-run.json. */
export const replayMode = () => replay;

const mode: Promise<boolean> = fetch(API_BASE + '/api/health', { signal: AbortSignal.timeout(1500) })
  .then((r) => r.ok)
  .catch(() => false)
  .then((ok) => (replay = !ok));

const recordedReport = (pr_id: string): Report => {
  const last = REC.runs[pr_id]?.find((e) => e.type === 'report');
  if (!last || last.type !== 'report') throw new Error(`No recorded run for ${pr_id}`);
  return last.report;
};

// Mirrors merge_gate.notify.parse_reply + handle_reply so a replayed reply reads exactly like a live one.
const ALIASES: Record<string, string> = {
  BLOCK: 'BLOCK', STOP: 'BLOCK', WHY: 'WHY', OK: 'OK', APPROVE: 'OK',
  FALSE: 'FALSE_ALARM', FALSE_ALARM: 'FALSE_ALARM', FP: 'FALSE_ALARM',
};
function replayReply(pr_id: string, text: string) {
  const r = recordedReport(pr_id);
  const words = text.trim().split(/\s+/).filter(Boolean).map((w) => w.toUpperCase().replace(/^[.!,?]+|[.!,?]+$/g, ''));
  const command = !words.length ? 'UNKNOWN'
    : words[0] === 'FALSE' && words[1] === 'ALARM' ? 'FALSE_ALARM'
      : ALIASES[words[0]] || 'UNKNOWN';
  const [action, out] =
    command === 'BLOCK' ? ['block_pr', `Blocked ${r.pr_id}.`]
      : command === 'WHY' ? ['send_text', [...(r.evidence.length ? r.evidence.map((e) => `${e.id}: ${e.detail}`) : ['No evidence recorded.']), `run ${r.run_hash}`].join('\n')]
        : command === 'OK' ? ['send_text', `Approve on GitHub with your own login: ${r.pr_id}`]
          : command === 'FALSE_ALARM' ? ['log_false_alarm', 'Thanks, logged. The gate will learn from it if held-out PRs agree.']
            : ['none', 'Reply BLOCK, WHY, OK or FALSE ALARM.'];
  return { command, action, text: out, github_blocked: false };
}

/** Live API call, or the recorded answer in replay mode (never touches the network then). */
const live = async <T,>(path: string, fromRecording: () => T, init?: RequestInit): Promise<T> =>
  (await mode) ? fromRecording() : j<T>(path, init);

export const getHealth = () => live('/api/health', () => REC.health);
export const getDemo = () => live('/api/demo', () => REC.demo);
export const getStats = () => live('/api/stats', () => REC.stats);
export const getMessage = (pr_id: string) =>
  live<{ to: Owner | null; text: string }>('/api/message', () => {
    const m = REC.messages[pr_id];
    if (!m) throw new Error(`No recorded message for ${pr_id}`);
    return m;
  }, { method: 'POST', body: JSON.stringify({ pr_id }) });
/** Sends the verdict to the code owner's real phone (Sendblue on the server; console if no keys). */
export const pageOwner = (pr_id: string, pr_url = '', github?: { repo: string; number: number }) =>
  live<{ to: Owner | null; text: string; sent: string | null }>('/api/message', () => {
    throw new Error('Paging a real phone needs the live gate (python -m merge_gate serve).');
  }, { method: 'POST', body: JSON.stringify({ pr_id, pr_url, github, send: true }) });
export const postReply = (pr_id: string, text: string, github?: { repo: string; number: number }) =>
  live<{ command: string; action: string; text: string; github_blocked: boolean }>('/api/reply',
    () => replayReply(pr_id, text),
    { method: 'POST', body: JSON.stringify({ pr_id, text, github }) });

/** Replays a recorded run with its real stage spacing, compressed to at most REPLAY_SECONDS. */
function replayGate(pr_id: string, onEvent: (e: RunEvent) => void): () => void {
  const events = REC.runs[pr_id];
  if (!events?.length) {
    onEvent({ type: 'error', error: `No recorded run for ${pr_id}`, t: 0 });
    return () => {};
  }
  const scale = Math.min(1, REPLAY_SECONDS / Math.max(events[events.length - 1].t, 0.001));
  // t is rescaled so the case clock tracks wall time; each stage's `ms` keeps its real recorded duration.
  const timers = events.map((e) => setTimeout(() => onEvent({ ...e, t: +(e.t * scale).toFixed(2) }), e.t * scale * 1000));
  return () => timers.forEach(clearTimeout);
}

/** Stream one real gate run (or its recording in replay mode). Returns a function that cancels it. */
export function runGate(pr_id: string, llm: boolean | null, onEvent: (e: RunEvent) => void): () => void {
  let cancel: (() => void) | null = null;
  let cancelled = false;
  mode.then((isReplay) => {
    if (cancelled) return;
    if (isReplay) { cancel = replayGate(pr_id, onEvent); return; }
    const q = new URLSearchParams({ pr_id });
    if (llm !== null) q.set('llm', llm ? '1' : '0');
    const es = new EventSource(`${API_BASE}/api/run?${q}`);
    es.onmessage = (m) => {
      const ev = JSON.parse(m.data) as RunEvent;
      onEvent(ev);
      if (ev.type === 'report' || ev.type === 'error') es.close();
    };
    es.onerror = () => {
      onEvent({ type: 'error', error: `lost connection to ${API_BASE}`, t: 0 });
      es.close();
    };
    cancel = () => es.close();
  });
  return () => { cancelled = true; cancel?.(); };
}

export const RULES: { id: string; short: string }[] = [
  { id: 'R1_DELETED_TEST', short: 'R1' },
  { id: 'R2_SKIPPED_TEST', short: 'R2' },
  { id: 'R3_WEAKENED_ASSERT', short: 'R3' },
  { id: 'R4_MOCKED_SUBJECT', short: 'R4' },
  { id: 'R5_HARDCODED_OUTPUT', short: 'R5' },
  { id: 'R6_OUT_OF_SCOPE_TEST_EDIT', short: 'R6' },
  { id: 'R7_DANGEROUS_CALL', short: 'R7' },
  { id: 'R8_BACKDOOR_LITERAL', short: 'R8' },
  { id: 'R9_UNPARSEABLE', short: 'R9' },
];

export const RULE_LABEL: Record<string, string> = {
  R1_DELETED_TEST: 'Test deleted',
  R2_SKIPPED_TEST: 'Test skipped',
  R3_WEAKENED_ASSERT: 'Assert weakened',
  R4_MOCKED_SUBJECT: 'Code under test mocked',
  R5_HARDCODED_OUTPUT: 'Hardcoded test value',
  R6_OUT_OF_SCOPE_TEST_EDIT: 'Out-of-scope test edit',
  R7_DANGEROUS_CALL: 'Dangerous call',
  R8_BACKDOOR_LITERAL: 'Backdoor literal',
  R9_UNPARSEABLE: 'Does not parse',
};
