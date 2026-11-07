/**
 * @license
 * SPDX-License-Identifier: Apache-2.0
 *
 * Merge Gate Reviewer - Full-Stack Server & AI Test Verifier Agent
 * Exposes /api/agent-verifier to run dynamic AI-driven test synthesis and
 * unique defect/suggestion discovery across any public GitHub code or PR diff.
 */

import express from 'express';
import { createServer as createViteServer } from 'vite';
import path from 'path';
import { fileURLToPath } from 'url';
import { GoogleGenAI, Type } from '@google/genai';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

const ai = new GoogleGenAI({
  apiKey: process.env.GEMINI_API_KEY,
  httpOptions: {
    headers: {
      'User-Agent': 'aistudio-build',
    },
  },
});

async function startServer() {
  const app = express();
  const PORT = 3000;

  app.use(express.json({ limit: '2mb' }));

  /**
   * POST /api/agent-verifier
   * Connects the Independent AI Verification Agent (gemini-3.8-flash) to dynamically
   * synthesize scenario-specific tests and detect unique errors & suggestions based on
   * the 5 Merge Gate Benchmark Verification Criteria.
   */
  app.post('/api/agent-verifier', async (req, res) => {
    try {
      const { prTitle, repo, issueDescription, publicInterface, files } = req.body || {};

      if (!files || !Array.isArray(files) || files.length === 0) {
        res.status(400).json({ error: 'Missing files payload for AI Test Agent analysis.' });
        return;
      }

      // Format file diffs with line numbers so the AI Test Agent can reference exact lines
      const formattedFiles = files
        .slice(0, 6)
        .map((file: any) => {
          const hunkText = (file.hunks || [])
            .map((hunk: any) => {
              let lineNum = hunk.newStart || 1;
              const numberedLines = (hunk.lines || []).slice(0, 180).map((l: string) => {
                const prefix = l.startsWith('-') ? 'DEL' : `L${lineNum}`;
                if (!l.startsWith('-')) lineNum++;
                return `${prefix}: ${l}`;
              });
              return numberedLines.join('\n');
            })
            .join('\n---\n');
          return `=== FILE: ${file.filename} ===\n${hunkText}`;
        })
        .join('\n\n');

      const prompt = `Analyze the following code change / GitHub repository file(s) as an Independent AI Verification & Test Agent for Merge Gate Reviewer.

Repository: ${repo || 'unknown/repo'}
Title: ${prTitle || 'Code Change'}
Context / Issue Spec: ${issueDescription || 'General code verification'}
Detected Public Signatures:
${publicInterface || 'N/A'}

Code / Diff with Line Numbers:
${formattedFiles}

Evaluate the code strictly against the 5 Merge Gate Benchmark Criteria AND Anti-Gaming rules:
1. RUNTIME_EXECUTION_INTEGRITY (AG-07): Code is not broken when trying to run (syntax errors, missing colons/brackets, broken/nonexistent imports, undefined variables, unhandled exceptions, division-by-zero, null/None dereference, type mismatches).
2. PERFORMANCE_REGRESSION (AG-08): Application performance is not slowed down (no nested O(N^2) loops over collections, blocking synchronous time.sleep/sleepSync, redundant DB/network calls inside loops, or unindexed scans).
3. COMPLEXITY_INFLATION (AG-09): Code simplicity is preserved so functions are not refactored into deeply nested conditional pyramids or high cyclomatic complexity.
4. STYLE_INCONSISTENCY (AG-10): Code style conventions match existing code styling (no camelCase in snake_case Python modules, no stripped type annotations, no ': any' escape hatches in TypeScript).
5. REGULATORY_STYLE_VIOLATION (AG-11) & ANTI-GAMING (AG-01..AG-06): Matches rules & regulations of code styling (no wildcard 'import *', no silent 'except: pass' or empty catch blocks, no leftover debug print()/console.log() in production code, and no deleted/skipped/weakened tests or hardcoded test return branches).

Tasks:
1. Dynamically generate 3 to 4 scenario-specific Independent Test Cases (IT-AI-101, IT-AI-102, etc.) that test the ACTUAL functions, parameters, and edge cases present in the provided code (never generic placeholder names). If the code has a bug, syntax error, performance trap, or logic flaw, mark the corresponding test as passed: false and show the concrete input, expected output, actual output, and failure trace.
2. Detect all specific violations across rules AG-01 through AG-11 with exact file name, line number, severity, description, and offending snippet.
3. Provide 2 to 4 actionable AI Agent Suggestions explaining how to fix the detected defects or harden the code based on the 5 criteria.`;

      const response = await ai.models.generateContent({
        model: 'gemini-3.8-flash',
        contents: prompt,
        config: {
          systemInstruction:
            'You are the Merge Gate Independent Verification Agent. You synthesize function-specific black-box test cases from code & public interfaces, execute static + behavioral trace reasoning, and pinpoint exact bugs, performance regressions, complexity inflation, and style/regulatory violations. Always return valid JSON matching the schema.',
          responseMimeType: 'application/json',
          responseSchema: {
            type: Type.OBJECT,
            properties: {
              agentSummary: {
                type: Type.STRING,
                description: 'Concise 1-2 sentence executive summary of what the AI Test Agent discovered in this specific code.',
              },
              synthesizedTests: {
                type: Type.ARRAY,
                items: {
                  type: Type.OBJECT,
                  properties: {
                    id: { type: Type.STRING, description: 'Test ID e.g. IT-AI-101' },
                    name: { type: Type.STRING, description: 'Specific test function name targeting the actual code' },
                    targetFunction: { type: Type.STRING, description: 'Actual function signature being tested' },
                    requirement: { type: Type.STRING, description: 'Specific behavioral or benchmark requirement verified' },
                    input: { type: Type.STRING, description: 'Concrete test input arguments JSON/repr' },
                    expected: { type: Type.STRING, description: 'Expected return value or behavior' },
                    actual: { type: Type.STRING, description: 'Actual output or failure observed in the code' },
                    passed: { type: Type.BOOLEAN, description: 'True if the code passes this test, false if a defect causes failure' },
                    durationMs: { type: Type.INTEGER, description: 'Estimated execution time in ms' },
                    errorTrace: { type: Type.STRING, description: 'Detailed assertion or runtime trace if passed is false' },
                  },
                  required: ['id', 'name', 'targetFunction', 'requirement', 'input', 'expected', 'actual', 'passed', 'durationMs'],
                },
              },
              detectedViolations: {
                type: Type.ARRAY,
                items: {
                  type: Type.OBJECT,
                  properties: {
                    ruleId: { type: Type.STRING, description: 'Rule ID from AG-01 to AG-11' },
                    ruleName: { type: Type.STRING, description: 'Rule name e.g. RUNTIME_EXECUTION_INTEGRITY, PERFORMANCE_REGRESSION, COMPLEXITY_INFLATION, STYLE_INCONSISTENCY, REGULATORY_STYLE_VIOLATION' },
                    severity: { type: Type.STRING, description: 'critical, high, or medium' },
                    file: { type: Type.STRING, description: 'Filename' },
                    line: { type: Type.INTEGER, description: '1-indexed line number where defect occurs' },
                    description: { type: Type.STRING, description: 'Specific explanation of the unique error found' },
                    snippet: { type: Type.STRING, description: 'Code line snippet' },
                  },
                  required: ['ruleId', 'ruleName', 'severity', 'file', 'line', 'description', 'snippet'],
                },
              },
              suggestions: {
                type: Type.ARRAY,
                items: {
                  type: Type.OBJECT,
                  properties: {
                    criterion: { type: Type.STRING, description: 'Which of the 5 criteria this suggestion addresses (Runtime, Performance, Simplicity, Style, or Regulatory)' },
                    file: { type: Type.STRING },
                    line: { type: Type.INTEGER },
                    title: { type: Type.STRING, description: 'Short title of the fix/suggestion' },
                    recommendation: { type: Type.STRING, description: 'Concrete explanation of how to fix or improve the code' },
                    suggestedPatch: { type: Type.STRING, description: '1-3 line code example of the clean fix' },
                  },
                  required: ['criterion', 'file', 'line', 'title', 'recommendation', 'suggestedPatch'],
                },
              },
            },
            required: ['agentSummary', 'synthesizedTests', 'detectedViolations', 'suggestions'],
          },
        },
      });

      const rawText = (response.text ?? '{}').trim();
      const parsed = JSON.parse(rawText);
      res.json(parsed);
    } catch (error: any) {
      console.error('AI Test Agent error:', error);
      res.status(500).json({
        error: error?.message || 'AI Test Agent execution failed.',
      });
    }
  });

  if (process.env.NODE_ENV !== 'production') {
    const vite = await createViteServer({
      server: { middlewareMode: true },
      appType: 'spa',
    });
    app.use(vite.middlewares);
  } else {
    const distPath = path.join(__dirname, 'dist');
    app.use(express.static(distPath));
    app.get('*all', (_req, res) => {
      res.sendFile(path.join(distPath, 'index.html'));
    });
  }

  app.listen(PORT, '0.0.0.0', () => {
    console.log(`Merge Gate Reviewer server listening on http://0.0.0.0:${PORT}`);
  });
}

startServer();
