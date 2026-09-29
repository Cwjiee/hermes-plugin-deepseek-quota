"""
deepseek-quota: shared in-memory usage store.

Tracks token consumption from post_api_request hook payloads and
exposes it to the tool handler and slash command.
"""

from __future__ import annotations

import threading
from collections import defaultdict
from typing import Dict

# ---------------------------------------------------------------------------
# Thread-safe usage accumulator
# ---------------------------------------------------------------------------

_lock = threading.Lock()

# Cumulative totals since plugin load (all sessions)
_lifetime: Dict[str, int] = defaultdict(int)

# Per-session totals: session_id → {model → {input/output/cache_read/cache_write}}
_sessions: Dict[str, Dict[str, Dict[str, int]]] = defaultdict(
    lambda: defaultdict(lambda: defaultdict(int))
)

# The session_id of the most-recent active session (best-effort)
_current_session: str = ""


def record(
    session_id: str,
    model: str,
    usage: dict,
) -> None:
    """Called by post_api_request hook to accumulate token counts."""
    global _current_session
    input_tokens: int = usage.get("input_tokens") or usage.get("prompt_tokens") or 0
    output_tokens: int = usage.get("output_tokens") or usage.get("completion_tokens") or 0
    cache_read: int = (
        usage.get("cache_read_input_tokens")
        or usage.get("prompt_cache_hit_tokens")
        or 0
    )
    cache_write: int = (
        usage.get("cache_creation_input_tokens")
        or usage.get("prompt_cache_miss_tokens")
        or 0
    )

    with _lock:
        _current_session = session_id or _current_session
        bucket = _sessions[session_id][model]
        bucket["input"] += input_tokens
        bucket["output"] += output_tokens
        bucket["cache_read"] += cache_read
        bucket["cache_write"] += cache_write

        _lifetime["input"] += input_tokens
        _lifetime["output"] += output_tokens
        _lifetime["cache_read"] += cache_read
        _lifetime["cache_write"] += cache_write
        _lifetime["requests"] += 1


def reset_session(session_id: str) -> None:
    """Clear data for a finished session."""
    with _lock:
        _sessions.pop(session_id, None)


def snapshot(session_id: str | None = None) -> dict:
    """Return a consistent snapshot of current usage data."""
    with _lock:
        sid = session_id or _current_session
        session_data = dict(_sessions.get(sid, {}))
        # Deep-copy the nested dicts so caller can't mutate shared state
        session_models: Dict[str, Dict[str, int]] = {
            m: dict(counts) for m, counts in session_data.items()
        }
        lifetime = dict(_lifetime)
    return {
        "session_id": sid,
        "session_models": session_models,
        "lifetime": lifetime,
    }
