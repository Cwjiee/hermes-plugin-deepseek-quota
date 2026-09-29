"""
deepseek-quota: tool handler and API balance fetch.
"""

from __future__ import annotations

import json
import logging
import os
from typing import Any

from . import usage_store as store

logger = logging.getLogger(__name__)

_BALANCE_URL = "https://api.deepseek.com/user/balance"


def _fetch_balance() -> dict:
    """Fetch live account balance from DeepSeek API. Returns parsed dict or error dict."""
    api_key = os.environ.get("DEEPSEEK_API_KEY", "")
    if not api_key:
        return {"error": "DEEPSEEK_API_KEY not set — cannot fetch balance"}

    try:
        import urllib.request

        req = urllib.request.Request(
            _BALANCE_URL,
            headers={"Authorization": f"Bearer {api_key}", "Accept": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=8) as resp:
            body = resp.read().decode("utf-8")
        return json.loads(body)
    except Exception as exc:  # noqa: BLE001
        logger.debug("deepseek-quota: balance fetch failed: %s", exc)
        return {"error": str(exc)}


def _fmt_balance(balance_data: dict) -> list[str]:
    """Format balance response into display lines."""
    if "error" in balance_data:
        return [f"  ⚠ Balance fetch failed: {balance_data['error']}"]

    lines: list[str] = []
    is_available: bool = balance_data.get("is_available", False)
    avail_str = "✓ Available" if is_available else "✗ Unavailable"
    lines.append(f"  Account status : {avail_str}")

    for entry in balance_data.get("balance_infos", []):
        currency = entry.get("currency", "?")
        total = entry.get("total_balance", "?")
        granted = entry.get("granted_balance", "?")
        topped = entry.get("topped_up_balance", "?")
        lines.append(
            f"  Balance ({currency})  : {total} total  "
            f"(granted: {granted}  topped-up: {topped})"
        )
    return lines


def _fmt_model_breakdown(session_models: dict[str, dict[str, int]]) -> list[str]:
    """Format per-model token breakdown lines."""
    if not session_models:
        return ["  (no API calls recorded this session)"]
    lines: list[str] = []
    for model, counts in sorted(session_models.items()):
        total = counts.get("input", 0) + counts.get("output", 0)
        lines.append(
            f"  {model}: in={counts.get('input', 0):,}  "
            f"out={counts.get('output', 0):,}  "
            f"cache_read={counts.get('cache_read', 0):,}  "
            f"cache_write={counts.get('cache_write', 0):,}  "
            f"total={total:,}"
        )
    return lines


def deepseek_quota_check(args: dict[str, Any], **kwargs: Any) -> str:
    """Handler for the deepseek_quota_check tool."""
    include_breakdown: bool = bool(args.get("include_session_breakdown", False))

    # Fetch balance and usage in parallel would be nice, but keep it simple
    balance_data = _fetch_balance()
    snap = store.snapshot()

    # ---- Summarise session totals ----
    session_input = sum(c.get("input", 0) for c in snap["session_models"].values())
    session_output = sum(c.get("output", 0) for c in snap["session_models"].values())
    session_cache_read = sum(c.get("cache_read", 0) for c in snap["session_models"].values())
    session_cache_write = sum(c.get("cache_write", 0) for c in snap["session_models"].values())
    session_total = session_input + session_output

    lt = snap["lifetime"]
    lifetime_total = lt.get("input", 0) + lt.get("output", 0)

    # ---- Build output ----
    lines: list[str] = ["=== DeepSeek Quota & Usage ===", ""]

    lines.append("Account Balance:")
    lines.extend(_fmt_balance(balance_data))
    lines.append("")

    lines.append(f"Session Tokens  (id: {snap['session_id'] or '—'}):")
    lines.append(f"  Input        : {session_input:,}")
    lines.append(f"  Output       : {session_output:,}")
    lines.append(f"  Cache read   : {session_cache_read:,}")
    lines.append(f"  Cache write  : {session_cache_write:,}")
    lines.append(f"  Total        : {session_total:,}")

    if include_breakdown:
        lines.append("")
        lines.append("  Per-model breakdown:")
        lines.extend("  " + l for l in _fmt_model_breakdown(snap["session_models"]))

    lines.append("")
    lines.append("Lifetime Tokens (since plugin load):")
    lines.append(f"  Input        : {lt.get('input', 0):,}")
    lines.append(f"  Output       : {lt.get('output', 0):,}")
    lines.append(f"  Cache read   : {lt.get('cache_read', 0):,}")
    lines.append(f"  Cache write  : {lt.get('cache_write', 0):,}")
    lines.append(f"  Total        : {lifetime_total:,}")
    lines.append(f"  API requests : {lt.get('requests', 0):,}")

    return json.dumps({"report": "\n".join(lines), "balance": balance_data, "usage": snap})
