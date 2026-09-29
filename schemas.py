"""Tool schema for the deepseek_quota_check tool."""

DEEPSEEK_QUOTA_CHECK = {
    "name": "deepseek_quota_check",
    "description": (
        "Check your DeepSeek provider account balance and token usage statistics. "
        "Returns the live account balance (from the DeepSeek API), total tokens consumed "
        "this session, and cumulative totals since the plugin was loaded. "
        "Use this whenever the user asks about their DeepSeek quota, balance, credits, "
        "or how many tokens they have used."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "include_session_breakdown": {
                "type": "boolean",
                "description": (
                    "If true, include per-model token breakdown for the current session. "
                    "Default: false."
                ),
            },
        },
        "required": [],
    },
}
