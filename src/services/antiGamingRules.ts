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
              /(sinon\.stub\([^)]+\)\.returns|mockReturnValueOnce\(true\))/.test(content)
            ) {
              violations.push({
                ruleId: 'AG-04',
                ruleName: 'MOCKED_CODE_UNDER_TEST',
                severity: 'critical',
                file: file.filename,
                line: lineNum,
                description: `Mocked target unit under test: "${content.slice(0, 70)}"`,
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
