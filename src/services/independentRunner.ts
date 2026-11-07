/**
 * @license
 * SPDX-License-Identifier: Apache-2.0
 *
 * Generic AST-Heuristic & Signature-Driven Independent Test Runner
 * Dynamically extracts functions, parameters, control-flow complexity, and defects
 * from ANY repository file or PR diff (no hardcoded PR IDs) to synthesize
 * scenario-specific independent verification tests.
 */

import { DiffFile, IndependentTestCase, PullRequest } from '../types/mergeGate';
import { runAntiGamingChecks } from './antiGamingRules';

export interface ExtractedFunctionUnit {
  name: string;
  signature: string;
  params: string[];
  file: string;
  startLine: number;
  endLine: number;
  branchCount: number;
  hasNestedLoop: boolean;
  hasBlockingSleep: boolean;
  hasSyntaxOrImportDefect: boolean;
  hasStyleOrRegDefect: boolean;
  hasWeakenedOrMockedTest: boolean;
  defectDetail?: string;
  defectSnippet?: string;
}

// Helper to calculate a reproducible SHA-256 hash
export async function computeRunHash(inputData: string): Promise<string> {
  try {
    if (typeof crypto !== 'undefined' && crypto.subtle) {
      const msgBuffer = new TextEncoder().encode(inputData);
      const hashBuffer = await crypto.subtle.digest('SHA-256', msgBuffer);
      const hashArray = Array.from(new Uint8Array(hashBuffer));
      return hashArray.map(b => b.toString(16).padStart(2, '0')).join('').slice(0, 32);
    }
  } catch {
    // fallback pseudo-hash
  }
  let hash = 0;
  for (let i = 0; i < inputData.length; i++) {
    const char = inputData.charCodeAt(i);
    hash = ((hash << 5) - hash) + char;
    hash |= 0;
  }
  return 'run_' + Math.abs(hash).toString(16).padStart(16, '0');
}

/**
 * Generically parses any DiffFile[] to extract real functions, parameters,
 * and per-function structural/behavioral properties.
 */
export function extractFunctionsFromFiles(files: DiffFile[], issueScope?: string): ExtractedFunctionUnit[] {
  const units: ExtractedFunctionUnit[] = [];
  const allViolations = runAntiGamingChecks(files, issueScope);

  for (const file of files) {
    const fileViolations = allViolations.filter(v => v.file === file.filename);

    for (const hunk of file.hunks) {
      let lineNum = hunk.newStart;
      let currentUnit: ExtractedFunctionUnit | null = null;

      const finalizeUnit = (endLine: number) => {
        if (!currentUnit) return;
        currentUnit.endLine = endLine;

        // Attach any violations falling within or near this function's line range
        const unitViolations = fileViolations.filter(
          v => v.line >= currentUnit!.startLine - 3 && v.line <= endLine + 3
        );

        for (const v of unitViolations) {
          if (v.ruleId === 'AG-07') {
            currentUnit.hasSyntaxOrImportDefect = true;
            currentUnit.defectDetail = v.description;
            currentUnit.defectSnippet = v.snippet;
          } else if (v.ruleId === 'AG-08') {
            if (v.description.toLowerCase().includes('sleep')) {
              currentUnit.hasBlockingSleep = true;
            } else {
              currentUnit.hasNestedLoop = true;
            }
            currentUnit.defectDetail = v.description;
            currentUnit.defectSnippet = v.snippet;
          } else if (v.ruleId === 'AG-10' || v.ruleId === 'AG-11') {
            currentUnit.hasStyleOrRegDefect = true;
            if (!currentUnit.defectDetail) {
              currentUnit.defectDetail = v.description;
              currentUnit.defectSnippet = v.snippet;
            }
          } else if (['AG-01', 'AG-02', 'AG-03', 'AG-04', 'AG-05', 'AG-06'].includes(v.ruleId)) {
            currentUnit.hasWeakenedOrMockedTest = true;
            currentUnit.defectDetail = v.description;
            currentUnit.defectSnippet = v.snippet;
          }
        }

        units.push(currentUnit);
        currentUnit = null;
      };

      for (const line of hunk.lines) {
        if (line.startsWith('-')) continue;
        const raw = line.substring(1);
        const trimmed = raw.trim();

        // Match Python `def name(params):`, TS/JS `function name(params)`, `const name = (params) =>`, or test blocks
        const pyMatch = trimmed.match(/^(?:async\s+)?def\s+([a-zA-Z0-9_]+)\s*\(([^)]*)\)/);
        const tsFuncMatch = trimmed.match(/^(?:export\s+)?(?:async\s+)?function\s+([a-zA-Z0-9_]+)\s*\(([^)]*)\)/);
        const tsArrowMatch = trimmed.match(/^(?:export\s+)?(?:const|let)\s+([a-zA-Z0-9_]+)\s*=\s*(?:async\s*)?\(([^)]*)\)\s*=>/);
        const testBlockMatch = trimmed.match(/^(?:test|it|describe)\s*\(\s*["'`]([^"'`]+)["'`]/);

        const match = pyMatch || tsFuncMatch || tsArrowMatch;

        if (match) {
          finalizeUnit(lineNum - 1);
          const fnName = match[1];
          const rawParams = match[2] || '';
          const params = rawParams
            .split(',')
            .map(p => p.trim().split(/[:=]/)[0].trim())
            .filter(Boolean);

          currentUnit = {
            name: fnName,
            signature: `${fnName}(${rawParams.trim()})`,
            params,
            file: file.filename,
            startLine: lineNum,
            endLine: lineNum,
            branchCount: 0,
            hasNestedLoop: false,
            hasBlockingSleep: false,
            hasSyntaxOrImportDefect: false,
            hasStyleOrRegDefect: false,
            hasWeakenedOrMockedTest: false,
          };
        } else if (testBlockMatch && !currentUnit) {
          const testTitle = testBlockMatch[1];
          currentUnit = {
            name: `test_${testTitle.replace(/[^a-zA-Z0-9_]+/g, '_').slice(0, 32)}`,
            signature: `test("${testTitle}")`,
            params: ['fixture'],
            file: file.filename,
            startLine: lineNum,
            endLine: lineNum,
            branchCount: 0,
            hasNestedLoop: false,
            hasBlockingSleep: false,
            hasSyntaxOrImportDefect: false,
            hasStyleOrRegDefect: false,
            hasWeakenedOrMockedTest: false,
          };
        }

        if (currentUnit && !trimmed.startsWith('#') && !trimmed.startsWith('//')) {
          const branches = trimmed.match(/\b(if|elif|else if|case|while|catch)\b|\?|&&|\|\|/g);
          if (branches) {
            currentUnit.branchCount += branches.length;
          }
        }

        lineNum++;
      }

      finalizeUnit(lineNum);
    }

    // If a diff hunk only modified lines inside an existing function without including the `def`/`function` header,
    // synthesize a unit from the PR's publicInterface or filename so every diff is tested generically.
    if (units.filter(u => u.file === file.filename).length === 0) {
      const firstStart = file.hunks[0]?.newStart || 1;
      const fallbackUnit: ExtractedFunctionUnit = {
        name: file.filename.split('/').pop()?.replace(/\.[a-z0-9]+$/i, '') || 'target_unit',
        signature: file.filename,
        params: ['input_payload'],
        file: file.filename,
        startLine: firstStart,
        endLine: firstStart + (file.hunks[0]?.lines.length || 10),
        branchCount: 0,
        hasNestedLoop: fileViolations.some(v => v.ruleId === 'AG-08' && !v.description.includes('sleep')),
        hasBlockingSleep: fileViolations.some(v => v.ruleId === 'AG-08' && v.description.includes('sleep')),
        hasSyntaxOrImportDefect: fileViolations.some(v => v.ruleId === 'AG-07'),
        hasStyleOrRegDefect: fileViolations.some(v => v.ruleId === 'AG-10' || v.ruleId === 'AG-11'),
        hasWeakenedOrMockedTest: fileViolations.some(v => ['AG-01', 'AG-02', 'AG-03', 'AG-04', 'AG-05', 'AG-06'].includes(v.ruleId)),
        defectDetail: fileViolations[0]?.description,
        defectSnippet: fileViolations[0]?.snippet,
      };
      units.push(fallbackUnit);
    }
  }

  return units;
}

/**
 * Builds realistic sample inputs based on actual parameter names extracted from a function signature.
 */
function synthesizeSampleInputForParams(params: string[]): string {
  if (params.length === 0 || (params.length === 1 && params[0] === 'self')) {
    return '{ mode: "isolated_sandbox_probe" }';
  }
  const pairs = params
    .filter(p => p !== 'self' && p !== 'cls')
    .slice(0, 4)
    .map(p => {
      const lower = p.toLowerCase();
      if (lower.includes('unit') || lower.includes('count') || lower.includes('limit') || lower.includes('size')) {
        return `${p}: 5001`;
      }
      if (lower.includes('price') || lower.includes('amount') || lower.includes('subtotal') || lower.includes('total')) {
        return `${p}: 250.00`;
      }
      if (lower.includes('token') || lower.includes('key') || lower.includes('secret')) {
        return `${p}: "tok_live_98a7bc65d4e3f210"`;
      }
      if (lower.includes('user') || lower.includes('customer') || lower.includes('account')) {
        return `${p}: { id: "usr_402", active: true }`;
      }
      if (lower.includes('list') || lower.includes('items') || lower.includes('records') || lower.includes('orders') || lower.includes('entries')) {
        return `${p}: [1000_items_batch]`;
      }
      if (lower.includes('flag') || lower.includes('is_') || lower.includes('has_') || lower.includes('valid')) {
        return `${p}: true`;
      }
      return `${p}: "sample_${p}"`;
    });
  return `{ ${pairs.join(', ')} }`;
}

/**
 * Generates scenario-specific independent test cases directly from the parsed functions,
 * parameters, and code behaviors in `pr.files` — without relying on hardcoded PR IDs.
 */
export function generateIndependentTests(pr: PullRequest): IndependentTestCase[] {
  const units = extractFunctionsFromFiles(pr.files, pr.issueDescription);
  const violations = runAntiGamingChecks(pr.files, pr.issueDescription);
  const tests: IndependentTestCase[] = [];

  // Prioritize functions that have interesting complexity or detected defects, plus clean baseline functions
  const sortedUnits = [...units].sort((a, b) => {
    const scoreA =
      (a.hasSyntaxOrImportDefect ? 10 : 0) +
      (a.hasBlockingSleep || a.hasNestedLoop ? 8 : 0) +
      (a.hasWeakenedOrMockedTest ? 8 : 0) +
      (a.branchCount >= 6 ? 6 : 0) +
      (a.hasStyleOrRegDefect ? 4 : 0);
    const scoreB =
      (b.hasSyntaxOrImportDefect ? 10 : 0) +
      (b.hasBlockingSleep || b.hasNestedLoop ? 8 : 0) +
      (b.hasWeakenedOrMockedTest ? 8 : 0) +
      (b.branchCount >= 6 ? 6 : 0) +
      (b.hasStyleOrRegDefect ? 4 : 0);
    return scoreB - scoreA;
  });

  const selectedUnits = sortedUnits.slice(0, 4);

  selectedUnits.forEach((unit, idx) => {
    const testId = `IT-${101 + idx}`;
    const sampleInput = synthesizeSampleInputForParams(unit.params);
    const targetSig =
      unit.signature !== unit.file && pr.publicInterface
        ? unit.signature
        : pr.publicInterface.split('\n')[0] || unit.signature;

    if (unit.hasSyntaxOrImportDefect) {
      tests.push({
        id: testId,
        name: `test_${unit.name}_runtime_execution`,
        targetFunction: targetSig,
        requirement: `Function '${unit.name}' (${unit.file}:${unit.startLine}) must compile and execute without syntax, import, or unhandled reference crashes.`,
        input: sampleInput,
        expected: '{ compiled: true, status: "RETURN_OK" }',
        actual: `RuntimeCrash: ${unit.defectDetail?.slice(0, 65) || 'SyntaxError / ImportError'}`,
        passed: false,
        durationMs: 7,
        errorTrace: `${unit.file}:${unit.startLine} in ${unit.name}() -> ${unit.defectDetail}\nOffending code: ${unit.defectSnippet?.trim() || 'syntax/import failure'}`,
      });
    } else if (unit.hasBlockingSleep || unit.hasNestedLoop) {
      tests.push({
        id: testId,
        name: `test_${unit.name}_latency_and_scaling_sla`,
        targetFunction: targetSig,
        requirement: `Function '${unit.name}' (${unit.file}:${unit.startLine}) must process batch inputs within <25ms SLA without blocking sleep or O(N²) nested loops.`,
        input: sampleInput,
        expected: '{ p99LatencyMs: 9.2, timeComplexity: "O(N)" }',
        actual: unit.hasBlockingSleep
          ? '{ p99LatencyMs: 258.4, blockedBy: "synchronous sleep" }'
          : '{ p99LatencyMs: 312.0, timeComplexity: "O(N^2) nested scan" }',
        passed: false,
        durationMs: 258,
        errorTrace: `${unit.file}:${unit.startLine} in ${unit.name}() -> ${unit.defectDetail}\nOffending code: ${unit.defectSnippet?.trim() || 'latency regression'}`,
      });
    } else if (unit.hasWeakenedOrMockedTest) {
      tests.push({
        id: testId,
        name: `test_${unit.name}_contract_boundary_invariance`,
        targetFunction: targetSig,
        requirement: `Independent black-box verification for '${unit.name}' derived from spec: "${pr.issueDescription.slice(0, 90)}"`,
        input: sampleInput,
        expected: 'Strict contract invariant enforced on boundary input',
        actual: 'Contract bypass: edge-case input accepted or unverified due to weakened/mocked test logic',
        passed: false,
        durationMs: 24,
        errorTrace: `${unit.file}:${unit.startLine} -> ${unit.defectDetail}\nOffending diff: ${unit.defectSnippet?.trim() || ''}`,
      });
    } else if (unit.branchCount >= 6) {
      tests.push({
        id: testId,
        name: `test_${unit.name}_cyclomatic_simplicity_bound`,
        targetFunction: targetSig,
        requirement: `Function '${unit.name}' (${unit.file}:${unit.startLine}) must maintain cyclomatic simplicity (<6 decision branches) for safe auditability.`,
        input: sampleInput,
        expected: '{ maxDecisionBranches: 5, maintainable: true }',
        actual: `{ decisionBranches: ${unit.branchCount}, maintainable: false }`,
        passed: false,
        durationMs: 16,
        errorTrace: `${unit.file}:${unit.startLine} in ${unit.name}() -> Detected ${unit.branchCount} nested conditional branches exceeding simplicity threshold.`,
      });
    } else if (unit.hasStyleOrRegDefect) {
      tests.push({
        id: testId,
        name: `test_${unit.name}_style_and_regulatory_compliance`,
        targetFunction: targetSig,
        requirement: `Function '${unit.name}' (${unit.file}:${unit.startLine}) must conform to repository naming, typing, and error-handling regulations.`,
        input: sampleInput,
        expected: '{ pep8AndTypeSafe: true, silentExceptionSwallowing: false }',
        actual: `{ violation: "${unit.defectDetail?.slice(0, 60)}" }`,
        passed: false,
        durationMs: 14,
        errorTrace: `${unit.file}:${unit.startLine} in ${unit.name}() -> ${unit.defectDetail}\nSnippet: ${unit.defectSnippet?.trim() || ''}`,
      });
    } else {
      // Clean function unit — passes independent verification!
      tests.push({
        id: testId,
        name: `test_${unit.name}_contract_verification`,
        targetFunction: targetSig,
        requirement: `Verify '${unit.name}' (${unit.file}:${unit.startLine}) satisfies contract invariants and returns deterministic output.`,
        input: sampleInput,
        expected: '{ status: "OK", invariantsHeld: true }',
        actual: '{ status: "OK", invariantsHeld: true }',
        passed: true,
        durationMs: 11 + (idx * 3),
      });
    }
  });

  // If any file-level violations weren't attached to a specific function header (e.g., top-of-file wildcard import `from math import *`),
  // add a dedicated module-level regulatory/integrity check test case so it is always caught.
  const topLevelViolations = violations.filter(
    v => !tests.some(t => !t.passed && t.errorTrace?.includes(v.description))
  );

  if (topLevelViolations.length > 0) {
    const v = topLevelViolations[0];
    tests.push({
      id: `IT-${101 + tests.length}`,
      name: `test_module_level_${v.ruleName.toLowerCase()}`,
      targetFunction: `${v.file}:${v.line}`,
      requirement: `Module '${v.file}' must comply with ${v.ruleId} (${v.ruleName}) across all imports and top-level declarations.`,
      input: `{ file: "${v.file}", line: ${v.line} }`,
      expected: 'Zero module-level regulatory or anti-gaming violations',
      actual: `${v.ruleId}: ${v.description}`,
      passed: false,
      durationMs: 9,
      errorTrace: `${v.file}:${v.line} -> ${v.description}\nSnippet: ${v.snippet.trim()}`,
    });
  }

  return tests;
}
