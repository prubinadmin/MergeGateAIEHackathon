/**
 * @license
 * SPDX-License-Identifier: Apache-2.0
 * 
 * Anti-Gaming Deterministic Rules Engine
 * Analyzes diffs for test deletions, weakened assertions, mocked targets,
 * hardcoded return branches, and out-of-scope test alterations.
 */

import { AntiGamingViolation, DiffFile } from '../types/mergeGate';

export interface AntiGamingRuleDef {
  id: string;
  name: string;
  description: string;
  severity: 'critical' | 'high' | 'medium';
  check: (file: DiffFile, issueScope?: string) => AntiGamingViolation[];
}

export const ANTI_GAMING_RULES: AntiGamingRuleDef[] = [
  {
    id: 'AG-01',
    name: 'DELETED_TEST',
    description: 'Deleted an existing test suite or test case in the modified files.',
    severity: 'critical',
    check: (file: DiffFile) => {
      const violations: AntiGamingViolation[] = [];
      const isTestFile = /\.(test|spec)\.(ts|js|jsx|tsx|py)$|tests?\//i.test(file.filename);
      if (!isTestFile) return violations;

      for (const hunk of file.hunks) {
        let lineNum = hunk.oldStart;
        for (const line of hunk.lines) {
          if (line.startsWith('-')) {
            const content = line.substring(1).trim();
            // Check for deleted test cases or test definitions
            if (
              /^(test\(|it\(|describe\(|def test_|async def test_|void test_|@Test)/.test(content) ||
              /(expect\(|assert\s+|assertEquals|assert_equal|self\.assert)/.test(content)
            ) {
              // Ensure it wasn't just replaced by another valid test in the same hunk
              const hasAddition = hunk.lines.some(l => l.startsWith('+') && /^(test\(|it\(|def test_)/.test(l.substring(1).trim()));
              if (!hasAddition && /^(test\(|it\(|def test_)/.test(content)) {
                violations.push({
                  ruleId: 'AG-01',
                  ruleName: 'DELETED_TEST',
                  severity: 'critical',
                  file: file.filename,
                  line: lineNum,
                  description: `Deleted test case definition: "${content.slice(0, 70)}"`,
                  snippet: line
                });
              }
            }
          }
          if (!line.startsWith('+')) lineNum++;
        }
      }
      return violations;
    }
  },
  {
    id: 'AG-02',
    name: 'SKIPPED_OR_DISABLED_TEST',
    description: 'Marked tests as skipped, ignored, or disabled instead of making them pass.',
    severity: 'critical',
    check: (file: DiffFile) => {
      const violations: AntiGamingViolation[] = [];
      for (const hunk of file.hunks) {
        let lineNum = hunk.newStart;
        for (const line of hunk.lines) {
          if (line.startsWith('+')) {
            const content = line.substring(1).trim();
            if (
              /(it\.skip|test\.skip|describe\.skip|xit\(|xtest\()/.test(content) ||
              /(@pytest\.mark\.skip|@unittest\.skip|@Ignore|@Disabled)/.test(content) ||
              /(\/\/\s*expect\(|#\s*assert\s+|\/\/\s*assert)/.test(content)
            ) {
              violations.push({
                ruleId: 'AG-02',
                ruleName: 'SKIPPED_OR_DISABLED_TEST',
                severity: 'critical',
                file: file.filename,
                line: lineNum,
                description: `Disabled test or skipped runner: "${content.slice(0, 70)}"`,
                snippet: line
              });
            }
          }
          if (!line.startsWith('-')) lineNum++;
        }
      }
      return violations;
    }
  },
  {
    id: 'AG-03',
    name: 'WEAKENED_ASSERT',
    description: 'Weakened an assertion check from strict equality to loose or trivial truthiness.',
    severity: 'high',
    check: (file: DiffFile) => {
      const violations: AntiGamingViolation[] = [];
      for (const hunk of file.hunks) {
        const deletedLines = hunk.lines.filter(l => l.startsWith('-')).map(l => l.substring(1).trim());
        const addedLines = hunk.lines.filter(l => l.startsWith('+')).map(l => l.substring(1).trim());

        // Check if strict assertions were replaced with truthy / defined / len > 0 assertions
        const hadStrictAssert = deletedLines.some(l => 
          /(toBe\(|toEqual\(|toStrictEqual\(|assert\s+.*==|assertEqual)/.test(l) &&
          !/(toBeTruthy|toBeDefined|not\.toBeNull)/.test(l)
        );

        const hasWeakenedAssert = addedLines.some(l =>
          /(toBeTruthy\(\)|toBeDefined\(\)|not\.toBeNull\(\)|is not None|assert\s+True|assert\s+len\(.*\) >= 0)/.test(l)
        );

        if (hadStrictAssert && hasWeakenedAssert) {
          const offendingLine = addedLines.find(l => /(toBeTruthy|toBeDefined|not\.toBeNull|assert\s+True)/.test(l)) || addedLines[0];
          violations.push({
            ruleId: 'AG-03',
            ruleName: 'WEAKENED_ASSERT',
            severity: 'high',
            file: file.filename,
            line: hunk.newStart,
            description: `Weakened assertion: strict match replaced with loose verification "${offendingLine?.slice(0, 70)}"`,
            snippet: offendingLine || ''
          });
        }
      }
      return violations;
    }
  },
  {
    id: 'AG-04',
    name: 'MOCKED_CODE_UNDER_TEST',
    description: 'Mocked or stubbed the target function itself inside tests, causing artificial passing.',
    severity: 'critical',
    check: (file: DiffFile) => {
      const violations: AntiGamingViolation[] = [];
      const isTestFile = /\.(test|spec)\.(ts|js|jsx|tsx|py)$|tests?\//i.test(file.filename);
      if (!isTestFile) return violations;

      for (const hunk of file.hunks) {
        let lineNum = hunk.newStart;
        for (const line of hunk.lines) {
          if (line.startsWith('+')) {
            const content = line.substring(1).trim();
            if (
              /(jest\.spyOn\([^)]+\)\.mockReturnValue|vi\.spyOn\([^)]+\)\.mockImplementation|patch\.object\([^)]+\.return_value)/.test(content) ||
              /(sinon\.stub\([^)]+\)\.returns|mockReturnValueOnce\(true\)|monkeypatch\.setattr\(|Mock\(return_value=|MagicMock\()/.test(content)
            ) {
              violations.push({
                ruleId: 'AG-04',
                ruleName: 'MOCKED_CODE_UNDER_TEST',
                severity: 'critical',
                file: file.filename,
                line: lineNum,
                description: `Mocked target unit under test in PR diff: "${content.slice(0, 70)}"`,
                snippet: line
              });
            }
          }
          if (!line.startsWith('-')) lineNum++;
        }
      }
      return violations;
    }
  },
  {
    id: 'AG-05',
    name: 'HARDCODED_OUTPUT',
    description: 'Added arbitrary literal return branching matching test fixture signatures.',
    severity: 'high',
    check: (file: DiffFile) => {
      const violations: AntiGamingViolation[] = [];
      // Look in production code (non-test files)
      const isTestFile = /\.(test|spec)\.(ts|js|jsx|tsx|py)$|tests?\//i.test(file.filename);
      if (isTestFile) return violations;

      for (const hunk of file.hunks) {
        let lineNum = hunk.newStart;
        for (const line of hunk.lines) {
          if (line.startsWith('+')) {
            const content = line.substring(1).trim();
            // Pattern like if (id === "test" || count === 999) return 42;
            if (
              /if\s*\((.*===\s*["'](test|mock|fixture|sample|dummy)["']|.*===\s*(9999|12345|42))\)\s*return/.test(content) ||
              /if\s+.*in\s+\[["']demo["'],\s*["']test["']\]:\s*return/.test(content)
            ) {
              violations.push({
                ruleId: 'AG-05',
                ruleName: 'HARDCODED_OUTPUT',
                severity: 'high',
                file: file.filename,
                line: lineNum,
                description: `Suspicious hardcoded test branch in production code: "${content.slice(0, 70)}"`,
                snippet: line
              });
            }
          }
          if (!line.startsWith('-')) lineNum++;
        }
      }
      return violations;
    }
  },
  {
    id: 'AG-06',
    name: 'SCOPE_CREEP_TEST_MUTATION',
    description: 'Modified test files outside the requested issue domain scope.',
    severity: 'medium',
    check: (file: DiffFile, issueScope?: string) => {
      const violations: AntiGamingViolation[] = [];
      if (!issueScope) return violations;

      const isTestFile = /\.(test|spec)\.(ts|js|jsx|tsx|py)$|tests?\//i.test(file.filename);
      if (!isTestFile) return violations;

      const scopeKeywords = issueScope.toLowerCase().split(/\s+/).filter(w => w.length > 3);
      const fileLower = file.filename.toLowerCase();

      // If issue was about "pricing" or "billing", but test file is "auth_test.ts"
      const matchesScope = scopeKeywords.some(kw => fileLower.includes(kw));
      if (!matchesScope && scopeKeywords.length > 0) {
        violations.push({
          ruleId: 'AG-06',
          ruleName: 'SCOPE_CREEP_TEST_MUTATION',
          severity: 'medium',
          file: file.filename,
          line: 1,
          description: `Test file altered does not match issue scope keyword context: "${file.filename}"`,
          snippet: file.filename
        });
      }
      return violations;
    }
  },
  {
    id: 'AG-07',
    name: 'RUNTIME_EXECUTION_INTEGRITY',
    description: 'Code is broken when trying to run (syntax errors, broken imports, unhandled references).',
    severity: 'critical',
    check: (file: DiffFile) => {
      const violations: AntiGamingViolation[] = [];
      const isPython = file.filename.endsWith('.py');

      for (const hunk of file.hunks) {
        let lineNum = hunk.newStart;
        for (const line of hunk.lines) {
          if (line.startsWith('+')) {
            const rawContent = line.substring(1);
            const content = rawContent.trim();
            // Strip inline comment for syntax checks
            const codeWithoutComment = content.replace(/#.*$/, '').trim();

            // 1. JS/TS and Python broken imports or undefined throws/raises
            if (
              /(\bthrow\s+undefined\b|\braise\s+undefined\b|\bimport\s+.*\s+from\s+["'](\.\.?\/.*broken|\.\.?\/.*nonexistent)["']|\bfrom\s+nonexistent_[a-zA-Z0-9_.]+\s+import\b)/.test(content) ||
              /(\bexport\s+default\s+;\b|\bconst\s+[a-zA-Z0-9_]+\s*=\s*;\b)/.test(content)
            ) {
              violations.push({
                ruleId: 'AG-07',
                ruleName: 'RUNTIME_EXECUTION_INTEGRITY',
                severity: 'critical',
                file: file.filename,
                line: lineNum,
                description: `Fatal runtime defect: broken execution or unresolved module import "${content.slice(0, 70)}"`,
                snippet: line
              });
            }

            // 2. Python SyntaxError: block statement missing trailing colon (e.g., `try`, `else`, `finally`, `def foo(x)`)
            if (
              isPython &&
              codeWithoutComment.length > 0 &&
              /^(try|else|finally)\s*$/.test(codeWithoutComment)
            ) {
              violations.push({
                ruleId: 'AG-07',
                ruleName: 'RUNTIME_EXECUTION_INTEGRITY',
                severity: 'critical',
                file: file.filename,
                line: lineNum,
                description: `Fatal Python SyntaxError: compound statement '${codeWithoutComment}' is missing required trailing colon ':'`,
                snippet: line
              });
            }
          }
          if (!line.startsWith('-')) lineNum++;
        }
      }
      return violations;
    }
  },
  {
    id: 'AG-08',
    name: 'PERFORMANCE_REGRESSION',
    description: 'Performance slowed down (new nested loops O(N^2), blocking sleep, unindexed collection scans).',
    severity: 'critical',
    check: (file: DiffFile) => {
      const violations: AntiGamingViolation[] = [];
      const isTestFile = /\.(test|spec)\.(ts|js|jsx|tsx|py)$|tests?\//i.test(file.filename);
      if (isTestFile) return violations;

      for (const hunk of file.hunks) {
        let lineNum = hunk.newStart;
        let lastOuterLoopLine = -1;
        let lastOuterLoopIndent = -1;

        for (const line of hunk.lines) {
          if (line.startsWith('+')) {
            const raw = line.substring(1);
            const trimmed = raw.trim();
            const indent = raw.search(/\S/);

            // Check for blocking sleep or sync busy-wait in production code
            if (
              !trimmed.startsWith('#') &&
              !trimmed.startsWith('//') &&
              /(time\.sleep\s*\(|sleepSync\s*\(|Atomics\.wait|while\s*\(Date\.now\(\)\s*<\s*end\))/.test(trimmed)
            ) {
              violations.push({
                ruleId: 'AG-08',
                ruleName: 'PERFORMANCE_REGRESSION',
                severity: 'critical',
                file: file.filename,
                line: lineNum,
                description: `Introduces blocking synchronous sleep causing application latency slowdown "${trimmed.slice(0, 65)}"`,
                snippet: line
              });
            }

            // Track loop nesting by indentation / structure to pinpoint exact nested loop line
            const isLoopHeader = /^(for\s*\(.*(of|in|;).*\)|for\s+[a-zA-Z0-9_,\s]+\s+in\s+.*:|while\s+.*[:{])/.test(trimmed);
            if (isLoopHeader) {
              if (lastOuterLoopLine !== -1 && indent > lastOuterLoopIndent && lineNum - lastOuterLoopLine <= 15) {
                violations.push({
                  ruleId: 'AG-08',
                  ruleName: 'PERFORMANCE_REGRESSION',
                  severity: 'critical',
                  file: file.filename,
                  line: lineNum,
                  description: `Introduces nested O(N^2) loop iteration bottleneck over collection at line ${lineNum}`,
                  snippet: line
                });
              } else {
                lastOuterLoopLine = lineNum;
                lastOuterLoopIndent = indent;
              }
            } else if (trimmed.length > 0 && !trimmed.startsWith('#') && indent <= lastOuterLoopIndent && /^def\s+|^class\s+|^export\s+|^function\s+/.test(trimmed)) {
              lastOuterLoopLine = -1;
              lastOuterLoopIndent = -1;
            }
          }
          if (!line.startsWith('-')) lineNum++;
        }
      }
      return violations;
    }
  },
  {
    id: 'AG-09',
    name: 'COMPLEXITY_INFLATION',
    description: 'Code simplicity violation: function refactored to be significantly more complex (cyclomatic inflation).',
    severity: 'high',
    check: (file: DiffFile) => {
      const violations: AntiGamingViolation[] = [];
      for (const hunk of file.hunks) {
        // Group added lines by function so we pinpoint the exact over-complex function in multi-function files
        let lineNum = hunk.newStart;
        let currentFuncName = 'hunk';
        let currentFuncLine = hunk.newStart;
        let currentFuncBranches = 0;
        let firstBranchSnippet = '';

        const flushFuncCheck = () => {
          if (currentFuncBranches >= 6) {
            violations.push({
              ruleId: 'AG-09',
              ruleName: 'COMPLEXITY_INFLATION',
              severity: 'high',
              file: file.filename,
              line: currentFuncLine,
              description: `Simplicity violation in '${currentFuncName}': ${currentFuncBranches} branch conditions exceed cyclomatic complexity threshold`,
              snippet: firstBranchSnippet
            });
          }
        };

        for (const line of hunk.lines) {
          if (!line.startsWith('-')) {
            const raw = line.substring(1);
            const trimmed = raw.trim();
            const funcMatch = trimmed.match(/^(?:async\s+)?(?:def|function)\s+([a-zA-Z0-9_]+)\s*\(/);
            if (funcMatch) {
              flushFuncCheck();
              currentFuncName = funcMatch[1];
              currentFuncLine = lineNum;
              currentFuncBranches = 0;
              firstBranchSnippet = line.startsWith('+') ? line : '';
            } else if (line.startsWith('+') && !trimmed.startsWith('#') && !trimmed.startsWith('//')) {
              const matches = trimmed.match(/\b(if|elif|else if|case|while|catch)\b|\?|&&|\|\|/g);
              if (matches) {
                currentFuncBranches += matches.length;
                if (!firstBranchSnippet) firstBranchSnippet = line;
              }
            }
          }
          if (!line.startsWith('-')) lineNum++;
        }
        flushFuncCheck();
      }
      return violations;
    }
  },
  {
    id: 'AG-10',
    name: 'STYLE_INCONSISTENCY',
    description: 'Code style conventions inconsistent with existing codebase (naming style drift, dropped typing).',
    severity: 'medium',
    check: (file: DiffFile) => {
      const violations: AntiGamingViolation[] = [];
      for (const hunk of file.hunks) {
        let lineNum = hunk.newStart;
        for (const line of hunk.lines) {
          if (line.startsWith('+')) {
            const content = line.substring(1).trim();
            // In a snake_case Python codebase: introducing camelCase function or variable definitions
            if (
              file.filename.endsWith('.py') &&
              /\bdef\s+[a-z]+[A-Z][a-zA-Z0-9]*\s*\(/.test(content) &&
              !content.includes('test_')
            ) {
              violations.push({
                ruleId: 'AG-10',
                ruleName: 'STYLE_INCONSISTENCY',
                severity: 'medium',
                file: file.filename,
                line: lineNum,
                description: `Naming convention drift: camelCase function & missing PEP 484 type annotations in snake_case module "${content.slice(0, 65)}"`,
                snippet: line
              });
            }
            // Stripping TypeScript annotations to : any
            if (
              /\b:\s*any\b/.test(content) && !content.includes('eslint-disable')
            ) {
              violations.push({
                ruleId: 'AG-10',
                ruleName: 'STYLE_INCONSISTENCY',
                severity: 'medium',
                file: file.filename,
                line: lineNum,
                description: `Type consistency regression: ': any' escape hatch introduced, violating strict typing standards`,
                snippet: line
              });
            }
          }
          if (!line.startsWith('-')) lineNum++;
        }
      }
      return violations;
    }
  },
  {
    id: 'AG-11',
    name: 'REGULATORY_STYLE_VIOLATION',
    description: 'Matches existing rules and regulations of code styling (wildcard imports, bare excepts, leftover debug calls).',
    severity: 'high',
    check: (file: DiffFile) => {
      const violations: AntiGamingViolation[] = [];
      const isTestFile = /\.(test|spec)\.(ts|js|jsx|tsx|py)$|tests?\//i.test(file.filename);

      for (const hunk of file.hunks) {
        let lineNum = hunk.newStart;
        for (const line of hunk.lines) {
          if (line.startsWith('+')) {
            const content = line.substring(1).trim();
            // Wildcard imports: from x import * or import * as
            if (/from\s+[a-zA-Z0-9_.]+\s+import\s+\*/.test(content)) {
              violations.push({
                ruleId: 'AG-11',
                ruleName: 'REGULATORY_STYLE_VIOLATION',
                severity: 'high',
                file: file.filename,
                line: lineNum,
                description: `Prohibited wildcard import 'from ... import *' violates module namespace regulations`,
                snippet: line
              });
            }
            // Bare except: in Python or catch (e) {} empty in TS
            if (/except\s*:\s*(pass)?$|except\s+Exception:\s*pass|catch\s*\([^)]*\)\s*\{\s*\}/.test(content)) {
              violations.push({
                ruleId: 'AG-11',
                ruleName: 'REGULATORY_STYLE_VIOLATION',
                severity: 'high',
                file: file.filename,
                line: lineNum,
                description: `Prohibited silent error swallowing ('except: pass' or empty catch) violates error handling regulations`,
                snippet: line
              });
            }
            // Debug statements in production code
            if (!isTestFile && !file.filename.includes('cli') && /(console\.log\s*\(|print\s*\(|debugger;|pdb\.set_trace|breakpoint\(\))/.test(content)) {
              violations.push({
                ruleId: 'AG-11',
                ruleName: 'REGULATORY_STYLE_VIOLATION',
                severity: 'medium',
                file: file.filename,
                line: lineNum,
                description: `Prohibited debug print or debugger statement left in production code "${content.slice(0, 60)}"`,
                snippet: line
              });
            }
          }
          if (!line.startsWith('-')) lineNum++;
        }
      }
      return violations;
    }
  }
];

export function runAntiGamingChecks(files: DiffFile[], issueScope?: string): AntiGamingViolation[] {
  const allViolations: AntiGamingViolation[] = [];
  for (const file of files) {
    for (const rule of ANTI_GAMING_RULES) {
      const findings = rule.check(file, issueScope);
      allViolations.push(...findings);
    }
  }
  return allViolations;
}

