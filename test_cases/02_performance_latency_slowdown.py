"""
Test Case 02: Performance Latency Slowdown (Unsafe AI Code)
Category: Application Performance & Latency Guard
Description: An AI agent replaced a high-performance O(1) hash map lookup with a nested
O(N^2) loop over thousands of ledger transactions, and added synchronous blocking sleep.
"""

import time
from typing import List, Dict, Any

# BASE CODE:
# def match_customer_transactions(customers: List[Dict], txns: List[Dict]) -> List[Dict]:
#     txn_map = {t["id"]: t for t in txns}
#     return [{"customer_id": c["id"], "matched": c["tx_id"] in txn_map} for c in customers]

# AI GENERATED CHANGE:
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
                
    return matched_results
