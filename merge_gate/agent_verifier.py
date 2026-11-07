"""
Merge Gate Reviewer - Independent AI Test Agent Connector (Python Backend)

This module defines the hook point for connecting an LLM-powered Test & Verification Agent
to dynamically generate scenario-specific tests and detect unique errors or refactoring
suggestions across arbitrary GitHub Pull Requests or repository files.

Where to Connect Your Test Agent:
1. Web / Full-Stack UI:
   - Server Endpoint: `POST /api/agent-verifier` in `/server.ts` (uses `@google/genai` SDK with `gemini-3.8-flash`)
   - Client Service: `runAiTestVerifierAgent(pr)` in `/src/services/aiTestAgent.ts`
   - Generic AST Fallback: `generateIndependentTests(pr)` in `/src/services/independentRunner.ts`
2. Python CLI / GitHub Action (`merge_gate/`):
   - Call `run_ai_agent_verification(diff_text, issue_spec)` in this file from `merge_gate/verify.py`.
"""

import json
import os
from typing import Any, Dict, List


BENCHMARK_CRITERIA_PROMPT = """
You are the Merge Gate Independent AI Test Agent.
Analyze the provided code or diff against the 5 Benchmark Verification Criteria:
1. RUNTIME_EXECUTION_INTEGRITY (R10 / AG-07): Code is not broken when trying to run.
2. PERFORMANCE_REGRESSION (R11 / AG-08): Application performance is not slowed down (no O(N^2) loops or blocking sleep).
3. COMPLEXITY_INFLATION (R12 / AG-09): Functions remain simple without deeply nested conditional pyramids.
4. STYLE_INCONSISTENCY (R13 / AG-10): Naming conventions and type annotations match existing codebase style.
5. REGULATORY_STYLE_VIOLATION (R14 / AG-11): No wildcard imports, bare `except: pass`, or leftover debug prints.
"""


def run_ai_agent_verification(
    code_or_diff: str,
    filepath: str = "module.py",
    issue_spec: str = "Verify runtime safety, performance, simplicity, and style compliance.",
) -> Dict[str, Any]:
    """
    Hook point for executing an AI Test Agent in Python (e.g., via google-genai SDK).
    If GEMINI_API_KEY is configured in the environment and `google-genai` is installed,
    queries Gemini to synthesize dynamic tests and code suggestions; otherwise returns
    structured hook metadata.
    """
    api_key = os.environ.get("GEMINI_API_KEY")
    if api_key:
        try:
            from google import genai  # type: ignore

            client = genai.Client(api_key=api_key)
            response = client.models.generate_content(
                model="gemini-3.8-flash",
                contents=(
                    f"{BENCHMARK_CRITERIA_PROMPT}\n\n"
                    f"File: {filepath}\nIssue Spec: {issue_spec}\n\n"
                    f"Code/Diff:\n{code_or_diff}\n\n"
                    "Return JSON with keys: agentSummary, synthesizedTests, detectedViolations, suggestions."
                ),
            )
            text = (response.text or "{}").strip()
            return json.loads(text)
        except Exception as exc:
            return {
                "agentSummary": f"AI Agent fallback triggered ({exc})",
                "synthesizedTests": [],
                "detectedViolations": [],
                "suggestions": [],
            }

    return {
        "agentSummary": "Set GEMINI_API_KEY to enable live Python AI Test Agent verification.",
        "synthesizedTests": [],
        "detectedViolations": [],
        "suggestions": [],
    }
