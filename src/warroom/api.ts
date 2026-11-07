// Client for the real Merge Gate API (`python -m merge_gate serve`). Nothing here simulates a result.

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
  routed_by?: 'subq' | 'blame';
  route_confidence?: number | null;
  urgency?: '' | 'page' | 'fyi';
  urgency_p?: number | null;
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

export type StageName = 'rules' | 'owners' | 'testgen' | 'decide' | 'routing' | 'summary';
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

export const getHealth = () => j<{ ok: boolean; llm: boolean }>('/api/health');
export const getDemo = () => j<DemoPr[]>('/api/demo');
export const getStats = () => j<Stats>('/api/stats');
export const getMessage = (pr_id: string) =>
  j<{ to: Owner | null; text: string }>('/api/message', { method: 'POST', body: JSON.stringify({ pr_id }) });
/** Sends the verdict to the code owner's real phone (Sendblue on the server; console if no keys). */
export const pageOwner = (pr_id: string, pr_url = '', github?: { repo: string; number: number }) =>
  j<{ to: Owner | null; text: string; sent: string | null }>('/api/message', {
    method: 'POST',
    body: JSON.stringify({ pr_id, pr_url, github, send: true }),
  });
export const postReply =(pr_id: string, text: string, github?: { repo: string; number: number }) =>
  j<{ command: string; action: string; text: string; github_blocked: boolean }>('/api/reply', {
    method: 'POST',
    body: JSON.stringify({ pr_id, text, github }),
  });

/** Stream one real gate run. Returns a function that cancels it. */
export function runGate(pr_id: string, llm: boolean | null, onEvent: (e: RunEvent) => void): () => void {
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
  return () => es.close();
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
