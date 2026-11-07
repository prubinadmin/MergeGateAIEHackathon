// Client for the real Merge Gate API (`python -m merge_gate serve`). Nothing here simulates a result:
// without a backend it replays a real recorded run and says so.

export const API_BASE: string =
  (import.meta as any).env?.VITE_MERGE_GATE_API || 'http://127.0.0.1:8787';

// The demo PRs also live in a real GitHub repo; a BLOCK from the owner's phone fails that PR's merge-gate check.
export const DEMO_GITHUB_REPO: string =
  (import.meta as any).env?.VITE_DEMO_GITHUB_REPO || 'Michaelwei08/merge-gate-demo-shop';
// demo PR id -> PR number in the GitHub demo repo (#4 there was a closed CI probe, so demo-4 is #5).
const DEMO_PR_NUMBERS: Record<string, number> = { 'demo-1': 1, 'demo-2': 2, 'demo-3': 3, 'demo-4': 5 };
export function githubFor(pr_id: string): { repo: string; number: number } | undefined {
  const n = DEMO_PR_NUMBERS[pr_id];
  return n && DEMO_GITHUB_REPO ? { repo: DEMO_GITHUB_REPO, number: n } : undefined;
}
export const prUrl = (pr_id: string) => {
  const g = githubFor(pr_id);
  return g ? `https://github.com/${g.repo}/pull/${g.number}` : '';
};

/** Owner replies recorded by the live gate (phone replies via /api/sendblue included). Live mode only. */
export async function getReplies(): Promise<{ hash: string; data: { pr_id: string; owner: string; command: string; raw: string; action: string } }[]> {
  const res = await fetch(API_BASE + '/api/log');
  if (!res.ok) return [];
  const body = await res.json();
  return (body.records || []).filter((r: any) => r.kind === 'reply');
}

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
// Captured from `python -m merge_gate serve` with curl into recorded-run.json (loaded only when needed).
type Health = { ok: boolean; llm: boolean };
type ReplyResult = { command: string; action: string; text: string; github_blocked: boolean };
interface Recording {
  recorded_at: string;
  health: Health;
  demo: DemoPr[];
  stats: Stats;
  runs: Record<string, RunEvent[]>;
  messages: Record<string, { to: Owner | null; text: string }>;
  replies: Record<string, Record<string, ReplyResult>>;
}
const REPLAY_SECONDS = 8;
const REPROBE_MS = 5000;

function checkRecording(x: unknown): Recording {
  const r = (x ?? {}) as Partial<Recording>;
  if (typeof r.recorded_at !== 'string' || !r.health || !Array.isArray(r.demo) || !r.stats
    || !r.runs || !r.messages || !r.replies) throw new Error('recorded-run.json is missing required fields');
  return r as Recording;
}

async function probe(): Promise<Health | null> {
  const ac = new AbortController();
  const timer = setTimeout(() => ac.abort(), 1500);
  try {
    const res = await fetch(API_BASE + '/api/health', { signal: ac.signal });
    return res.ok ? ((await res.json()) as Health) : null;
  } catch {
    return null;
  } finally {
    clearTimeout(timer);
  }
}

// A public page must never reach for the visitor's loopback (no Local Network Access prompt).
const localPage = ['localhost', '127.0.0.1', '[::1]'].includes(location.hostname);
const loopbackApi = /^https?:\/\/(localhost|127\.0\.0\.1|\[::1\])(:\d+)?(\/|$)/.test(API_BASE);

let rec: Recording | null = null;
let health: Health | null = null;
let stats: Stats | null = null; // replay-session counters, start from the recorded stats
let replay = false;
const listeners = new Set<() => void>();
/** True while the page is replaying recorded-run.json instead of talking to a live gate. */
export const replayMode = () => replay;
export const recordedAt = () => rec?.recorded_at ?? '';
/** Notified when replay mode flips (e.g. the gate came up on localhost). Returns an unsubscribe. */
export const subscribeMode = (f: () => void) => { listeners.add(f); return () => { listeners.delete(f); }; };

const mode: Promise<void> = (async () => {
  health = !localPage && loopbackApi ? null : await probe();
  if (health) return;
  rec = checkRecording((await import('./recorded-run.json')).default);
  stats = { ...rec.stats };
  replay = true;
  if (!localPage) return;
  const timer = setInterval(async () => {
    const h = await probe();
    if (!h || !replay) return;
    clearInterval(timer);
    health = h;
    replay = false;
    listeners.forEach((f) => f());
  }, REPROBE_MS);
})();

/** Live API call, or the recorded answer in replay mode (never touches the network then). */
const live = async <T,>(path: string, fromRecording: (r: Recording) => T, init?: RequestInit): Promise<T> => {
  await mode;
  return replay && rec ? fromRecording(rec) : j<T>(path, init);
};

/** Reuses the probe's answer instead of asking /api/health twice. */
export const getHealth = async (): Promise<Health> => {
  await mode;
  return replay && rec ? rec.health : health ?? j<Health>('/api/health');
};
export const getDemo = () => live('/api/demo', (r) => r.demo);
export const getStats = () => live('/api/stats', () => ({ ...stats! }));
export const getMessage = (pr_id: string) =>
  live<{ to: Owner | null; text: string }>('/api/message', (r) => {
    const m = r.messages[pr_id];
    if (!m) throw new Error(`No recorded message for ${pr_id}`);
    return m;
  }, { method: 'POST', body: JSON.stringify({ pr_id }) });
/** Sends the verdict to the code owner's real phone (Sendblue on the server; console if no keys). */
export const pageOwner = (pr_id: string, pr_url = '', github?: { repo: string; number: number }) =>
  live<{ to: Owner | null; text: string; sent: string | null }>('/api/message', () => {
    throw new Error('Paging a real phone needs the live gate (python -m merge_gate serve).');
  }, { method: 'POST', body: JSON.stringify({ pr_id, pr_url, github, send: true }) });
/** In replay, returns the real server's recorded answer to that exact reply. */
export const postReply = (pr_id: string, text: string, github?: { repo: string; number: number }) =>
  live<ReplyResult>('/api/reply', (r) => {
    const out = r.replies[pr_id]?.[text.trim().toUpperCase()];
    if (!out) throw new Error(`No recorded reply "${text}" for ${pr_id}`);
    stats!.owner_replies += 1;
    if (out.action === 'block_pr') stats!.owner_blocks += 1;
    return out;
  }, { method: 'POST', body: JSON.stringify({ pr_id, text, github }) });

/** Replays a recorded run with its real stage spacing, compressed to at most REPLAY_SECONDS. */
function replayGate(r: Recording, pr_id: string, onEvent: (e: RunEvent) => void): () => void {
  const events = r.runs[pr_id];
  if (!events?.length) {
    onEvent({ type: 'error', error: `No recorded run for ${pr_id}`, t: 0 });
    return () => {};
  }
  const scale = Math.min(1, REPLAY_SECONDS / Math.max(events[events.length - 1].t, 0.001));
  // t is rescaled so the case clock tracks wall time; each stage's `ms` keeps its real recorded duration.
  const timers = events.map((e) => setTimeout(() => {
    if (e.type === 'report' && stats) {
      stats.checked += 1;
      stats.events += 1;
      if (e.report.verdict === 'BLOCK') stats.blocked += 1;
      else if (e.report.verdict === 'REVIEW') stats.review += 1;
      else stats.passed += 1;
    }
    onEvent({ ...e, t: +(e.t * scale).toFixed(2) });
  }, e.t * scale * 1000));
  return () => timers.forEach(clearTimeout);
}

/** Stream one real gate run (or its recording in replay mode). Returns a function that cancels it. */
export function runGate(pr_id: string, llm: boolean | null, onEvent: (e: RunEvent) => void): () => void {
  let cancel: (() => void) | null = null;
  let cancelled = false;
  mode.then(() => {
    if (cancelled) return;
    if (replay && rec) { cancel = replayGate(rec, pr_id, onEvent); return; }
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
  }).catch((e: Error) => { if (!cancelled) onEvent({ type: 'error', error: e.message, t: 0 }); });
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
