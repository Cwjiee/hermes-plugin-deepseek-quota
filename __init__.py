"""
deepseek-quota plugin — registration entry point.

Hooks:
  post_api_request  — accumulate token usage per request
  on_session_end    — log session summary; optionally warn on low balance

Tool:
  deepseek_quota_check — callable by the agent to surface balance + usage

Slash command:
  /deepseek-quota [balance|session|lifetime|reset] — direct user access
"""

from __future__ import annotations

import json
import logging
import os

from . import schemas, tools, usage_store as store

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Hooks
# ---------------------------------------------------------------------------

_LOW_BALANCE_THRESHOLD: float = 1.0  # overridden from config on register


def _on_post_api_request(
    session_id: str = "",
    model: str = "",
    provider: str = "",
    usage: dict | None = None,
    **_,
) -> None:
    """Accumulate token counts from every provider API response."""
    if not usage or provider.lower() not in ("deepseek", ""):
        # Only track DeepSeek calls; empty provider string = unknown, still track.
        # If provider is explicitly something else (openai, anthropic…), skip.
        if provider and provider.lower() != "deepseek":
            return
    store.record(session_id=session_id, model=model or "unknown", usage=usage or {})


def _on_session_end(
    session_id: str = "",
    completed: bool = True,
    **_,
) -> None:
    """Log a session summary and optionally warn on low balance."""
    snap = store.snapshot(session_id)
    lt = snap["lifetime"]
    s_input = sum(c.get("input", 0) for c in snap["session_models"].values())
    s_output = sum(c.get("output", 0) for c in snap["session_models"].values())
    s_total = s_input + s_output

    if s_total > 0:
        logger.info(
            "deepseek-quota session %s ended: in=%d out=%d total=%d "
            "(lifetime: in=%d out=%d requests=%d)",
            session_id,
            s_input,
            s_output,
            s_total,
            lt.get("input", 0),
            lt.get("output", 0),
            lt.get("requests", 0),
        )

    # Low-balance check (best-effort, never crash)
    if _LOW_BALANCE_THRESHOLD > 0 and s_total > 0:
        try:
            balance_data = tools._fetch_balance()
            for entry in balance_data.get("balance_infos", []):
                try:
                    total = float(entry.get("total_balance", "9999") or "9999")
                except ValueError:
                    continue
                if total < _LOW_BALANCE_THRESHOLD:
                    currency = entry.get("currency", "CNY")
                    logger.warning(
                        "deepseek-quota ⚠ LOW BALANCE: %.2f %s remaining "
                        "(threshold: %.2f). Top up at https://platform.deepseek.com/top_up",
                        total,
                        currency,
                        _LOW_BALANCE_THRESHOLD,
                    )
        except Exception as exc:  # noqa: BLE001
            logger.debug("deepseek-quota: low-balance check failed: %s", exc)

    # Keep session data in store (user may query after session ends); don't reset here.


# ---------------------------------------------------------------------------
# Slash command
# ---------------------------------------------------------------------------

_SLASH_HELP = """\
/deepseek-quota — DeepSeek quota & token usage

Subcommands:
  balance          Fetch live account balance from DeepSeek API
  session          Show token usage for the current session
  lifetime         Show cumulative token usage since plugin load
  reset            Clear all accumulated usage statistics
  help             Show this help

Examples:
  /deepseek-quota balance
  /deepseek-quota session
  /deepseek-quota lifetime
"""


def _cmd_balance() -> str:
    balance_data = tools._fetch_balance()
    lines = ["DeepSeek Account Balance:"]
    lines.extend(tools._fmt_balance(balance_data))
    return "\n".join(lines)


def _cmd_session() -> str:
    snap = store.snapshot()
    s_models = snap["session_models"]
    s_input = sum(c.get("input", 0) for c in s_models.values())
    s_output = sum(c.get("output", 0) for c in s_models.values())
    s_cache_r = sum(c.get("cache_read", 0) for c in s_models.values())
    s_cache_w = sum(c.get("cache_write", 0) for c in s_models.values())
    lines = [
        f"Session tokens (id: {snap['session_id'] or '—'}):",
        f"  Input      : {s_input:,}",
        f"  Output     : {s_output:,}",
        f"  Cache read : {s_cache_r:,}",
        f"  Cache write: {s_cache_w:,}",
        f"  Total      : {s_input + s_output:,}",
    ]
    if s_models:
        lines.append("\nPer-model:")
        lines.extend("  " + l for l in tools._fmt_model_breakdown(s_models))
    return "\n".join(lines)


def _cmd_lifetime() -> str:
    snap = store.snapshot()
    lt = snap["lifetime"]
    total = lt.get("input", 0) + lt.get("output", 0)
    lines = [
        "Lifetime tokens (since plugin load):",
        f"  Input      : {lt.get('input', 0):,}",
        f"  Output     : {lt.get('output', 0):,}",
        f"  Cache read : {lt.get('cache_read', 0):,}",
        f"  Cache write: {lt.get('cache_write', 0):,}",
        f"  Total      : {total:,}",
        f"  API calls  : {lt.get('requests', 0):,}",
    ]
    return "\n".join(lines)


def _cmd_reset() -> str:
    # Reset by clearing the private dicts directly through the store module
    with store._lock:
        store._lifetime.clear()
        store._sessions.clear()
        store._current_session = ""
    return "deepseek-quota: usage statistics reset."


def _handle_slash(raw_args: str) -> str:
    argv = raw_args.strip().split()
    sub = argv[0] if argv else "help"
    if sub in ("balance",):
        return _cmd_balance()
    if sub in ("session",):
        return _cmd_session()
    if sub in ("lifetime",):
        return _cmd_lifetime()
    if sub in ("reset",):
        return _cmd_reset()
    return _SLASH_HELP


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------

def register(ctx) -> None:
    """Wire tools, hooks, and slash command."""
    global _LOW_BALANCE_THRESHOLD
    try:
        _LOW_BALANCE_THRESHOLD = float(
            ctx.get_config("low_balance_warn_threshold", default=1.0) or 1.0
        )
    except (TypeError, ValueError):
        pass

    ctx.register_tool(
        name="deepseek_quota_check",
        toolset="deepseek-quota",
        schema=schemas.DEEPSEEK_QUOTA_CHECK,
        handler=tools.deepseek_quota_check,
    )

    ctx.register_hook("post_api_request", _on_post_api_request)
    ctx.register_hook("on_session_end", _on_session_end)

    ctx.register_command(
        "deepseek-quota",
        handler=_handle_slash,
        description="Check DeepSeek quota: balance, session & lifetime token usage.",
    )

    logger.info(
        "deepseek-quota loaded (low_balance_warn_threshold=%.2f CNY)",
        _LOW_BALANCE_THRESHOLD,
    )
