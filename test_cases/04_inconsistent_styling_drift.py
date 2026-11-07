"""
Production Module: Telemetry Ingestion & Payload Normalization Pipeline
File: test_cases/04_inconsistent_styling_drift.py

Most of this file (85%+) follows strict PEP 8 snake_case naming conventions
and complete static type annotations (`str`, `int`, `Dict`, `Optional`).
A small AI-generated addition nested around line 80 introduces camelCase
functions (`parseUserPayload`, `formatJsonResponse`) without type annotations.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Dict, List, Optional


MAX_METRIC_NAME_LEN = 128
DEFAULT_BATCH_LIMIT = 250


@dataclass(frozen=True)
class TelemetryEvent:
    metric_name: str
    value: float
    timestamp_ms: int
    host_tag: str


def validate_metric_identifier(metric_name: str) -> bool:
    """Checks that a metric name is non-empty and within length bounds."""
    if not metric_name or not isinstance(metric_name, str):
        return False
    stripped = metric_name.strip()
    return 0 < len(stripped) <= MAX_METRIC_NAME_LEN


def normalize_timestamp_millis(raw_timestamp: int) -> int:
    """Normalizes seconds-based timestamps to milliseconds if needed."""
    if raw_timestamp <= 0:
        raise ValueError("Timestamp must be positive")
    if raw_timestamp < 10_000_000_000:
        return raw_timestamp * 1000
    return raw_timestamp


def build_host_resource_tags(hostname: str, region: str = "us-west-2") -> Dict[str, str]:
    """Constructs standardized OpenTelemetry host resource tags."""
    clean_host = hostname.strip().lower() or "unknown-host"
    return {
        "host.name": clean_host,
        "cloud.region": region.strip().lower(),
        "telemetry.sdk.language": "python",
    }


def serialize_telemetry_event(event: TelemetryEvent) -> str:
    """Serializes a TelemetryEvent to a compact JSON line."""
    payload = {
        "metric": event.metric_name,
        "val": round(event.value, 4),
        "ts": event.timestamp_ms,
        "host": event.host_tag,
    }
    return json.dumps(payload, separators=(",", ":"))


# ==============================================================================
# AI AGENT MODIFICATION BELOW (Nested Defect inside existing working module)
# ==============================================================================
# DEFECT 1: camelCase function names (`parseUserPayload`, `formatJsonResponse`) in a strict snake_case module
# DEFECT 2: Stripped parameter and return type annotations
def parseUserPayload(rawData, maxBytes=4096):
    userRecordData = {}
    if len(rawData) > maxBytes:
        return None
    userRecordData["data"] = rawData
    return userRecordData


def formatJsonResponse(dataPayload, isSuccessFlag=True):
    return {"success": isSuccessFlag, "payload": dataPayload}


# ==============================================================================
# WORKING CODE CONTINUES BELOW
# ==============================================================================
def partition_events_by_host(events: List[TelemetryEvent]) -> Dict[str, List[TelemetryEvent]]:
    """Groups a batch of telemetry events by their source host tag."""
    grouped: Dict[str, List[TelemetryEvent]] = {}
    for ev in events:
        if not validate_metric_identifier(ev.metric_name):
            continue
        grouped.setdefault(ev.host_tag, []).append(ev)
    return grouped


def compute_batch_average(events: List[TelemetryEvent]) -> Optional[float]:
    """Computes the arithmetic mean of metric values in a non-empty batch."""
    if not events:
        return None
    total = sum(ev.value for ev in events)
    return round(total / len(events), 4)
