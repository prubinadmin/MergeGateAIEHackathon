/**
 * @license
 * SPDX-License-Identifier: Apache-2.0
 * 
 * Test Cases Suite & Issue Ticket Analyzer Service
 */

export interface TestCaseFile {
  id: string;
  filename: string;
  title: string;
  category: 'runtime' | 'performance' | 'simplicity' | 'style' | 'regulatory' | 'clean';
  categoryLabel: string;
  severity: 'CRITICAL' | 'HIGH' | 'MEDIUM' | 'CLEAN';
  verdict: 'BLOCK' | 'REVIEW' | 'PASS';
  ownerPaged: string;
  code: string;
  whyUnsafe: string;
  violations: Array<{
    ruleId: string;
    line: number;
    description: string;
  }>;
  remediation: string;
  safeRefactorSnippet: string;
}

export const TEST_SUITE_FILES: TestCaseFile[] = [
  {
    id: 'TC-01',
    filename: '01_broken_runtime_crash.py',
    title: 'Broken Runtime Execution & Fatal Syntax Crash',
    category: 'runtime',
    categoryLabel: '1. Runtime Execution Integrity',
    severity: 'CRITICAL',
    verdict: 'BLOCK',
    ownerPaged: 'TAAZ (@taaz · Security Lead)',
    code: `import sys
from nonexistent_internal_crypto_lib import BrokenCipherHandler # ERROR: Nonexistent module

def get_session_expiry(issued_at: float, ttl: int = 3600):
    try
        # Missing colon in try statement above causes syntax error
        cipher = BrokenCipherHandler()
        return cipher.compute_expiry(issued_at, ttl)
    except Exception as e:
        raise undefined # ERROR: 'undefined' is JavaScript, not valid Python name!`,
    whyUnsafe: 'The AI agent attempted a refactor but generated invalid Python syntax (missing colon) and referenced undefined runtime identifiers. Merging this PR will cause immediate crash-loop failures upon module import in production.',
    violations: [
      { ruleId: 'R10_RUNTIME_INTEGRITY', line: 5, description: 'Fatal SyntaxError: expected ":" at try statement' },
      { ruleId: 'R10_RUNTIME_INTEGRITY', line: 2, description: 'ModuleNotFoundError: cannot import from nonexistent_internal_crypto_lib' },
      { ruleId: 'R10_RUNTIME_INTEGRITY', line: 10, description: 'NameError: undefined identifier "undefined" used in exception handler' }
    ],
    remediation: 'Restore correct syntax formatting, import from standard authenticated crypto packages, and raise valid Python exception types.',
    safeRefactorSnippet: `from datetime import datetime, timezone

def get_session_expiry(issued_at: float, ttl: int = 3600) -> float:
    """Safe, strictly typed session expiration calculation."""
    if issued_at < 0 or ttl <= 0:
        raise ValueError("Invalid timestamp or TTL")
    return issued_at + ttl`
  },
  {
    id: 'TC-02',
    filename: '02_performance_latency_slowdown.py',
    title: 'Application Performance Latency & Quadratic O(N^2) Bottleneck',
    category: 'performance',
    categoryLabel: '2. Application Performance & Latency',
    severity: 'CRITICAL',
    verdict: 'BLOCK',
    ownerPaged: 'Peter Chen (@peter · Billing Lead)',
    code: `import time
from typing import List, Dict, Any

def match_customer_transactions(customers: List[Dict], txns: List[Dict]) -> List[Dict]:
    matched_results = []
    
    # DEFECT 1: Introduced blocking synchronous sleep inside transaction batch handler
    time.sleep(0.250) # SLOWDOWN: 250ms sleep halts server event thread!
    
    # DEFECT 2: Nested O(N^2) quadratic loop over unindexed collection
    for customer in customers:
        for txn in txns: # O(N * M) nested scan: for 10k users & 50k txns = 500,000,000 operations!
            if customer.get("tx_id") == txn.get("id"):
                matched_results.append({
                    "customer_id": customer["id"],
                    "txn_id": txn["id"],
                    "status": "matched"
                })
                break
                
    return matched_results`,
    whyUnsafe: 'The AI agent replaced an O(1) hash map lookup with a nested O(N*M) loop and inserted a 250ms synchronous blocking sleep. When executed against 10k customers and 50k transactions, this creates 500 million iterations and hangs the application process.',
    violations: [
      { ruleId: 'R11_PERFORMANCE_REGRESSION', line: 8, description: 'Synchronous time.sleep(0.250) blocks event thread, increasing API latency' },
      { ruleId: 'R11_PERFORMANCE_REGRESSION', line: 11, description: 'Nested O(N^2) loop iteration over unindexed transaction collection' }
    ],
    remediation: 'Eliminate synchronous sleep calls. Pre-index the transactions into an O(1) dictionary hash map prior to iterating customers.',
    safeRefactorSnippet: `from typing import List, Dict, Any

def match_customer_transactions(customers: List[Dict], txns: List[Dict]) -> List[Dict]:
    # Indexed in O(M) time, lookups in O(1) time
    txn_map = {t["id"]: t for t in txns if "id" in t}
    return [
        {"customer_id": c["id"], "txn_id": c["tx_id"], "status": "matched"}
        for c in customers if c.get("tx_id") in txn_map
    ]`
  },
  {
    id: 'TC-03',
    filename: '03_complexity_inflation_overengineered.py',
    title: 'Code Simplicity Violation & Cyclomatic Complexity Inflation',
    category: 'simplicity',
    categoryLabel: '3. Code Simplicity & Cyclomatic Complexity',
    severity: 'HIGH',
    verdict: 'BLOCK',
    ownerPaged: 'Peter Chen (@peter · Billing Lead)',
    code: `def calculate_discount(volume: int, tier: str) -> float:
    # DEFECT: Exploded cyclomatic complexity (+7 decision branches, 4 levels of nesting)
    discount = 0.0
    if tier is not None:
        if tier.strip().lower() == "enterprise":
            if volume > 500:
                if volume > 1000:
                    if volume > 5000:
                        discount = 0.35
                    else:
                        discount = 0.25
                else:
                    discount = 0.15
            else:
                discount = 0.05
        elif tier.strip().lower() == "standard":
            if volume > 100:
                if volume > 500:
                    discount = 0.12
                else:
                    discount = 0.08
            else:
                discount = 0.0
        else:
            discount = 0.0
    return discount`,
    whyUnsafe: 'The AI agent over-engineered a straightforward discount lookup into an impenetrable 8-branch decision tree with 5 levels of indentation. This cognitive complexity inflation drastically increases defect escape rates during subsequent maintenance.',
    violations: [
      { ruleId: 'R12_COMPLEXITY_INFLATION', line: 4, description: 'Function cyclomatic complexity inflated to 10 decision branches (threshold is 6)' },
      { ruleId: 'R12_COMPLEXITY_INFLATION', line: 7, description: 'Excessive nesting depth: 5 levels of nested if/elif statements' }
    ],
    remediation: 'Flatten the conditional branching into early guard clauses or a declarative tier discount threshold table.',
    safeRefactorSnippet: `TIER_RATES = {
    "enterprise": [(5000, 0.35), (1000, 0.25), (500, 0.15), (0, 0.05)],
    "standard": [(500, 0.12), (100, 0.08), (0, 0.0)]
}

def calculate_discount(volume: int, tier: str) -> float:
    rates = TIER_RATES.get((tier or "").strip().lower(), [])
    for threshold, rate in rates:
        if volume > threshold:
            return rate
    return 0.0`
  },
  {
    id: 'TC-04',
    filename: '04_inconsistent_styling_drift.py',
    title: 'Code Style Convention Drift & Dropped Static Type Annotations',
    category: 'style',
    categoryLabel: '4. Code Style Conventions Consistency',
    severity: 'MEDIUM',
    verdict: 'REVIEW',
    ownerPaged: 'Michael Vance (@michael · Core Lead)',
    code: `from typing import Optional

# DEFECT 1: camelCase function name in strict snake_case codebase
# DEFECT 2: Type annotations stripped, violating type safety regulations
def parseUserPayload(rawData, maxBytes=4096):
    userRecordData = {} # Inconsistent camelCase variable
    if len(rawData) > maxBytes:
        return None
    userRecordData["data"] = rawData
    return userRecordData

def formatJsonResponse(dataPayload, isSuccessFlag=True):
    # Inconsistent camelCase function violating repo conventions
    return {"success": isSuccessFlag, "payload": dataPayload}`,
    whyUnsafe: 'The AI agent introduced JavaScript-style camelCase identifiers into a strict PEP 8 Python repository and discarded all parameter and return type signatures, violating codebase consistency and breaking IDE type analysis.',
    violations: [
      { ruleId: 'R13_STYLE_INCONSISTENCY', line: 5, description: 'Function "parseUserPayload" violates snake_case convention in Python repository' },
      { ruleId: 'R13_STYLE_INCONSISTENCY', line: 5, description: 'Missing parameter and return type annotations on public function' },
      { ruleId: 'R13_STYLE_INCONSISTENCY', line: 12, description: 'Function "formatJsonResponse" violates snake_case naming conventions' }
    ],
    remediation: 'Rename methods and variables to snake_case and supply explicit static type annotations.',
    safeRefactorSnippet: `from typing import Optional, Dict, Any

def parse_user_payload(raw_data: str, max_bytes: int = 4096) -> Optional[Dict[str, Any]]:
    if len(raw_data) > max_bytes:
        return None
    return {"data": raw_data}

def format_json_response(data_payload: Dict[str, Any], is_success: bool = True) -> Dict[str, Any]:
    return {"success": is_success, "payload": data_payload}`
  },
  {
    id: 'TC-05',
    filename: '05_regulatory_rule_violation.py',
    title: 'Regulatory Violations: Wildcard Imports, Bare Except & Debug Prints',
    category: 'regulatory',
    categoryLabel: '5. Regulatory & Code Styling Regulations',
    severity: 'HIGH',
    verdict: 'BLOCK',
    ownerPaged: 'TAAZ (@taaz · Security Lead)',
    code: `# DEFECT 1: Wildcard import pollutes global namespace and bypasses linters
from auth.crypto import *

def validate_access_token(token: str) -> bool:
    try:
        # DEFECT 2: Debug print committed in production code
        print("[DEBUG TRACE] Validating sensitive token:", token)
        
        key = load_key("auth_v1")
        return verify_signature(token, key)
    except:
        # DEFECT 3: Bare except silently swallows cryptographic and memory errors!
        pass
        return False`,
    whyUnsafe: 'The AI agent introduced a wildcard namespace import, committed plain-text credential logging via print(), and added a bare except: pass clause that silently swallows memory corruptions and signature forged alerts.',
    violations: [
      { ruleId: 'R14_REGULATORY_STYLE_VIOLATION', line: 2, description: 'Wildcard import "from auth.crypto import *" violates module namespace regulation' },
      { ruleId: 'R14_REGULATORY_STYLE_VIOLATION', line: 7, description: 'Debug "print()" statement leaks security token payload in production code' },
      { ruleId: 'R14_REGULATORY_STYLE_VIOLATION', line: 11, description: 'Bare "except:" swallows fatal system and cryptographic verification exceptions' }
    ],
    remediation: 'Use explicit symbol imports. Remove debug prints. Catch specific CryptographicError exceptions and log via structured logger.',
    safeRefactorSnippet: `import logging
from auth.crypto import verify_signature, load_key, CryptographicError

logger = logging.getLogger(__name__)

def validate_access_token(token: str) -> bool:
    try:
        key = load_key("auth_v1")
        return verify_signature(token, key)
    except CryptographicError as e:
        logger.warning("Token verification failed: %s", e)
        return False`
  },
  {
    id: 'TC-06',
    filename: '06_clean_conforming_code.py',
    title: 'Clean Conforming Code (Safe Production Standard)',
    category: 'clean',
    categoryLabel: '6. All Benchmark Verifications Pass',
    severity: 'CLEAN',
    verdict: 'PASS',
    ownerPaged: 'Michael Vance (@michael · Core Lead)',
    code: `from typing import Dict, Any, Optional
import logging

logger = logging.getLogger(__name__)

def sanitize_account_identifier(raw_id: str) -> Optional[str]:
    """Sanitizes incoming customer UUID strings without regex backtracking."""
    if not raw_id or not isinstance(raw_id, str):
        return None
    cleaned = raw_id.strip()
    return cleaned if len(cleaned) <= 64 else None


def compute_tax_quote(subtotal_cents: int, jurisdiction_rate: float) -> Dict[str, Any]:
    """Calculates tax quote in O(1) time without nested branches or loops."""
    if subtotal_cents < 0:
        raise ValueError("Subtotal cents cannot be negative")
    if not (0.0 <= jurisdiction_rate <= 1.0):
        raise ValueError("Tax rate must be between 0.0 and 1.0")

    tax_cents = int(round(subtotal_cents * jurisdiction_rate))
    return {
        "subtotal_cents": subtotal_cents,
        "tax_cents": tax_cents,
        "total_cents": subtotal_cents + tax_cents,
        "jurisdiction_rate": jurisdiction_rate
    }`,
    whyUnsafe: 'All static verification benchmarks passed with zero defects. O(1) execution time, minimal cyclomatic complexity, full type safety, and standard logging.',
    violations: [],
    remediation: 'No changes required. Ready for automated merge gate clearance.',
    safeRefactorSnippet: '# Code is already optimal and safe.'
  }
];
