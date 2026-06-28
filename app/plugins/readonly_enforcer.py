"""ReadOnlyEnforcerPlugin — runtime guardrail ensuring PR Guardian never mutates GitHub.

This ADK plugin intercepts every tool call via before_tool_callback and blocks
any MCP tool whose name indicates a write or mutating operation.

## Enforcement strategy

With GitHub MCP as the sole external integration, we apply two rules:

1. Allowlist check: the tool name must be in GitHubMCPTool.ALL_READ_ONLY.
   Any tool not on this list is blocked, even if it looks read-only.

2. Prefix safeguard: even if the allowlist is bypassed, tool names starting
   with write-type prefixes (create_, update_, delete_, merge_, close_,
   add_, remove_, rename_, push_, patch_) are unconditionally blocked.

The plugin never throws — it returns an error dict so the LLM receives a
clear error message and can explain the refusal to the user.

## Local utility tools (pass-through)

parse_pr_url is a local Python function (not an MCP tool). It is visible
to the LLM as a regular ADK tool but makes no network calls. The plugin
allows it by name since it is read-only by construction.
"""

from __future__ import annotations

import logging
from typing import Any

from google.adk.plugins.base_plugin import BasePlugin
from google.adk.tools import BaseTool, ToolContext

from app.tools.mcp_tools import GitHubMCPTool

logger = logging.getLogger(__name__)

# Prefixes that unambiguously indicate write/mutate operations on GitHub MCP
_WRITE_PREFIXES = frozenset(
    {
        "create_",
        "update_",
        "delete_",
        "merge_",
        "close_",
        "add_",
        "remove_",
        "rename_",
        "push_",
        "patch_",
        "post_",
        "put_",
        "fork_",
        "star_",
        "unstar_",
        "dismiss_",
        "enable_",
        "disable_",
    }
)

# Local Python tools that are allowed unconditionally (no MCP network calls)
_LOCAL_TOOLS = frozenset(
    {"parse_pr_url", "transfer_to_agent", "finish_task", "set_model_response"}
)


class ReadOnlyEnforcerPlugin(BasePlugin):
    """Enforces the read-only invariant for PR Guardian at runtime.

    Blocks any GitHub MCP tool call that is not on the read-only allowlist.
    This is a hard runtime guard — not just a prompt instruction — ensuring
    the system can never approve, merge, comment on, or modify a PR even if
    the LLM is somehow convinced to attempt it.
    """

    def __init__(self) -> None:
        super().__init__(name="readonly_enforcer")

    async def before_tool_callback(
        self,
        *,
        tool: BaseTool,
        tool_args: dict[str, Any],
        tool_context: ToolContext,
    ) -> dict | None:
        """Inspect each tool call before execution.

        Returns None to allow the call, or an error dict to block it.
        """
        tool_name = tool.name

        # Always allow local utility tools
        if tool_name in _LOCAL_TOOLS:
            return None

        # Allow tools on the explicit read-only allowlist
        if tool_name in GitHubMCPTool.ALL_READ_ONLY:
            return None

        # Block anything with a write-type prefix
        if any(tool_name.startswith(prefix) for prefix in _WRITE_PREFIXES):
            return self._block(
                tool_name,
                reason=(
                    f"Tool '{tool_name}' starts with a write-operation prefix "
                    "and is not permitted in this read-only system."
                ),
            )

        # Block unknown tools not on the allowlist (fail-closed)
        return self._block(
            tool_name,
            reason=(
                f"Tool '{tool_name}' is not on the read-only allowlist. "
                "PR Guardian only permits explicit read-only GitHub MCP tools."
            ),
        )

    @staticmethod
    def _block(tool_name: str, reason: str) -> dict:
        msg = f"[ReadOnlyEnforcer] BLOCKED tool='{tool_name}': {reason}"
        logger.error(msg)
        return {
            "status": "error",
            "error": (
                "SAFETY VIOLATION: PR Guardian is read-only and advisory. "
                f"The attempted operation was blocked. Reason: {reason} "
                "If you believe this is an error, check the tool allowlist "
                "in app/plugins/readonly_enforcer.py."
            ),
        }
