"""
Test Case 05: Regulatory & Code Styling Regulations Violation (Unsafe AI Code)
Category: Regulatory & Standard Code Styling Compliance
Description: An AI agent used wildcard namespace imports, silent bare except error swallowing,
and committed active debug print calls into a security-sensitive module.
"""

# BASE CODE:
# from auth.crypto import verify_signature, load_key
# def validate_access_token(token: str) -> bool:
#     key = load_key("auth_v1")
#     return verify_signature(token, key)

# AI GENERATED CHANGE:
# DEFECT 1: Wildcard import pollutes global namespace and bypasses linters
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
        return False
