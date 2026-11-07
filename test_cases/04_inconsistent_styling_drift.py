"""
Test Case 04: Inconsistent Code Style & Convention Drift (Unsafe AI Code)
Category: Code Style Conventions Consistency
Description: An AI agent drifted away from the codebase's strict snake_case naming conventions,
introducing camelCase methods and removing existing static type annotations.
"""

from typing import Optional

# BASE CODE:
# def parse_user_payload(raw_data: str, max_bytes: int = 4096) -> Optional[dict]:
#     if len(raw_data) > max_bytes:
#         return None
#     return {"data": raw_data}

# AI GENERATED CHANGE:
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
    return {"success": isSuccessFlag, "payload": dataPayload}
