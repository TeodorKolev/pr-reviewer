"""GitHub MCP integration for PR Guardian.

This module is the SINGLE external integration point for all GitHub data access.
No agent calls the GitHub API directly — every GitHub interaction goes through
the GitHub MCP server via McpToolset.

## Architecture

  agent → McpToolset(tool_filter=[...]) → MCP stdio session → github-mcp-server → GitHub API

## Connection modes (set GITHUB_MCP_MODE env var)

  docker  (default)   Docker Desktop must be running.
                      docker pull ghcr.io/github/github-mcp-server
  binary              github-mcp-server binary must be on PATH.
                      Download from https://github.com/github/github-mcp-server/releases
  sse                 Set GITHUB_MCP_URL to your hosted MCP server URL.
                      Suitable for Cloud Run production deployments.
  http                Set GITHUB_MCP_URL to a streamable HTTP endpoint.

## Tool catalogue (GitHub MCP server)

  get_pull_request          PR metadata, head/base, merge state, draft status
  get_pull_request_files    List of changed files with patch per file
  get_pull_request_diff     Full unified diff of the PR
  get_pull_request_comments Review comments and inline annotations
  get_pull_request_reviews  Review submissions (approved, changes-requested, etc.)
  get_pull_request_status   CI check runs and combined commit status
  get_file_contents         Raw file content at a specific ref/branch
  get_repository            Repository metadata, settings, and default branch
  search_code               Code search within a repository (GitHub search syntax)
  get_issue                 Linked issue details

## Read-only enforcement

  ReadOnlyEnforcerPlugin (app/plugins/readonly_enforcer.py) inspects every
  before_tool_callback and blocks any tool whose name does NOT start with one
  of: get_, list_, search_. This is a hard runtime guardrail.
"""

from __future__ import annotations

import os
import re
from typing import TYPE_CHECKING

from google.adk.auth.auth_tool import AuthConfig
from google.adk.tools import BaseTool, FunctionTool
from google.adk.tools.base_toolset import BaseToolset
from google.adk.tools.mcp_tool.mcp_session_manager import (
    SseConnectionParams,
    StdioConnectionParams,
    StreamableHTTPConnectionParams,
)
from google.adk.tools.mcp_tool.mcp_toolset import McpToolset
from google.adk.tools.tool_context import ToolContext
from mcp import StdioServerParameters

if TYPE_CHECKING:
    pass

# ---------------------------------------------------------------------------
# GitHub MCP tool name constants
# All tool_filter lists reference these constants — never bare strings.
# ---------------------------------------------------------------------------


class GitHubMCPTool:
    """GitHub MCP server tool name constants.

    Reference: https://github.com/github/github-mcp-server
    """

    # Pull Request tools
    GET_PULL_REQUEST = "get_pull_request"
    GET_PULL_REQUEST_FILES = "get_pull_request_files"
    GET_PULL_REQUEST_DIFF = "get_pull_request_diff"
    GET_PULL_REQUEST_COMMENTS = "get_pull_request_comments"
    GET_PULL_REQUEST_REVIEWS = "get_pull_request_reviews"
    GET_PULL_REQUEST_STATUS = "get_pull_request_status"

    # File and content tools
    GET_FILE_CONTENTS = "get_file_contents"

    # Repository tools
    GET_REPOSITORY = "get_repository"

    # Search tools
    SEARCH_CODE = "search_code"

    # Issue tools
    GET_ISSUE = "get_issue"

    # All read-only tools (used by ReadOnlyEnforcerPlugin allowlist)
    ALL_READ_ONLY: frozenset[str] = frozenset(
        {
            GET_PULL_REQUEST,
            GET_PULL_REQUEST_FILES,
            GET_PULL_REQUEST_DIFF,
            GET_PULL_REQUEST_COMMENTS,
            GET_PULL_REQUEST_REVIEWS,
            GET_PULL_REQUEST_STATUS,
            GET_FILE_CONTENTS,
            GET_REPOSITORY,
            SEARCH_CODE,
            GET_ISSUE,
        }
    )


# ---------------------------------------------------------------------------
# Connection factory — reads environment to select the transport mode
# ---------------------------------------------------------------------------

_GITHUB_TOKEN_VAR = "GITHUB_TOKEN"
_GITHUB_MCP_MODE_VAR = "GITHUB_MCP_MODE"
_GITHUB_MCP_URL_VAR = "GITHUB_MCP_URL"
_GITHUB_MCP_BINARY_VAR = "GITHUB_MCP_BINARY"
_DOCKER_IMAGE = "ghcr.io/github/github-mcp-server"


def _make_connection_params() -> (
    StdioConnectionParams | SseConnectionParams | StreamableHTTPConnectionParams
):
    """Build MCP connection parameters from environment variables.

    Reads GITHUB_MCP_MODE (default: 'docker') and returns the appropriate
    connection params object. Called once per toolset construction.

    Environment variables:
        GITHUB_MCP_MODE:    'docker' | 'binary' | 'sse' | 'http'
        GITHUB_TOKEN:       GitHub Personal Access Token (all modes except sse/http)
        GITHUB_MCP_URL:     MCP server URL (sse and http modes)
        GITHUB_MCP_BINARY:  Path to github-mcp-server binary (binary mode, default: 'github-mcp-server')
    """
    mode = os.environ.get(_GITHUB_MCP_MODE_VAR, "docker").lower().strip()
    token = os.environ.get(_GITHUB_TOKEN_VAR, "")

    if mode == "sse":
        url = os.environ.get(_GITHUB_MCP_URL_VAR, "")
        if not url:
            raise ValueError(
                f"GITHUB_MCP_MODE=sse requires {_GITHUB_MCP_URL_VAR} to be set."
            )
        return SseConnectionParams(url=url)

    if mode == "http":
        url = os.environ.get(_GITHUB_MCP_URL_VAR, "")
        if not url:
            raise ValueError(
                f"GITHUB_MCP_MODE=http requires {_GITHUB_MCP_URL_VAR} to be set."
            )
        return StreamableHTTPConnectionParams(url=url)

    if mode == "binary":
        binary = os.environ.get(_GITHUB_MCP_BINARY_VAR, "github-mcp-server")
        return StdioConnectionParams(
            server_params=StdioServerParameters(
                command=binary,
                args=["stdio"],
                env={"GITHUB_PERSONAL_ACCESS_TOKEN": token},
            ),
            timeout=30,
        )

    # Default: docker
    return StdioConnectionParams(
        server_params=StdioServerParameters(
            command="docker",
            args=[
                "run",
                "-i",
                "--rm",
                "-e",
                "GITHUB_PERSONAL_ACCESS_TOKEN",
                _DOCKER_IMAGE,
            ],
            env={"GITHUB_PERSONAL_ACCESS_TOKEN": token},
        ),
        timeout=60,
    )


# ---------------------------------------------------------------------------
# Mock Toolset & Functions for Evaluation
# ---------------------------------------------------------------------------


async def get_pull_request(owner: str, repo: str, pullNumber: int) -> dict:
    """Fetch metadata for a GitHub Pull Request.

    Args:
        owner: The owner of the repository.
        repo: The repository name.
        pullNumber: The PR number.
    """
    pn = int(pullNumber)
    if pn == 101:
        return {
            "status": "success",
            "title": "Clean cache refactoring",
            "body": "Refactors the session cache to use standard dict. Fixes #101.",
            "user": {"login": "clean_coder"},
            "head": {"sha": "sha101", "ref": "feature/clean-cache"},
            "base": {"ref": "main"},
            "draft": False,
            "labels": [{"name": "type/refactor"}],
            "mergeable_state": "clean",
        }
    elif pn == 102:
        return {
            "status": "success",
            "title": "Add AWS credentials configuration",
            "body": "Integrates AWS connection settings. Closes #102.",
            "user": {"login": "cloud_integrator"},
            "head": {"sha": "sha102", "ref": "feature/aws-config"},
            "base": {"ref": "main"},
            "draft": False,
            "labels": [{"name": "type/feature"}],
            "mergeable_state": "clean",
        }
    elif pn == 103:
        return {
            "status": "success",
            "title": "Optimized parser logic",
            "body": "Optimizes parsing logic for high load. Resolves #103.",
            "user": {"login": "performance_guru"},
            "head": {"sha": "sha103", "ref": "feature/opt-parser"},
            "base": {"ref": "main"},
            "draft": False,
            "labels": [{"name": "type/perf"}],
            "mergeable_state": "clean",
        }
    elif pn == 104:
        return {
            "status": "success",
            "title": "Extend public API interface",
            "body": "Adds new public commands for daemon control.",
            "user": {"login": "fast_developer"},
            "head": {"sha": "sha104", "ref": "feature/public-api"},
            "base": {"ref": "main"},
            "draft": False,
            "labels": [{"name": "type/feature"}],
            "mergeable_state": "clean",
        }
    elif pn == 105:
        return {
            "status": "success",
            "title": "Support dynamic prompting",
            "body": "Supports dynamic query interpolation in system prompt template. Closes #105.",
            "user": {"login": "ai_enthusiast"},
            "head": {"sha": "sha105", "ref": "feature/dynamic-prompt"},
            "base": {"ref": "main"},
            "draft": False,
            "labels": [{"name": "type/feature"}],
            "mergeable_state": "clean",
        }
    return {
        "status": "error",
        "error": f"Pull request #{pn} not found in mock database.",
    }


async def get_pull_request_files(owner: str, repo: str, pullNumber: int) -> dict:
    """Fetch list of changed files for a pull request.

    Args:
        owner: The owner of the repository.
        repo: The repository name.
        pullNumber: The PR number.
    """
    pn = int(pullNumber)
    if pn == 101:
        return {
            "status": "success",
            "files": [
                {"filename": "app/cache.py", "additions": 10, "deletions": 5},
                {"filename": "tests/test_cache.py", "additions": 15, "deletions": 2},
            ],
        }
    elif pn == 102:
        return {
            "status": "success",
            "files": [
                {"filename": "config/settings.py", "additions": 20, "deletions": 0}
            ],
        }
    elif pn == 103:
        return {
            "status": "success",
            "files": [
                {"filename": "utils/parser.py", "additions": 100, "deletions": 20}
            ],
        }
    elif pn == 104:
        return {
            "status": "success",
            "files": [
                {"filename": "app/cli.py", "additions": 50, "deletions": 0}
            ],  # missing README.md or any docs / changelog changes
        }
    elif pn == 105:
        return {
            "status": "success",
            "files": [{"filename": "app/prompts.py", "additions": 15, "deletions": 2}],
        }
    return {"status": "error", "error": f"PR #{pn} files not found."}


async def get_pull_request_diff(owner: str, repo: str, pullNumber: int) -> dict:
    """Fetch unified diff for a pull request.

    Args:
        owner: The owner of the repository.
        repo: The repository name.
        pullNumber: The PR number.
    """
    pn = int(pullNumber)
    if pn == 101:
        return {
            "status": "success",
            "diff": 'diff --git a/app/cache.py b/app/cache.py\n--- a/app/cache.py\n+++ b/app/cache.py\n@@ -1,5 +1,10 @@\n-class CustomCache:\n-    def __init__(self):\n-        self._data = {}\n+def get_cached_val(key: str) -> str:\n+    """Get cached value by key."""\n+    return _CACHE.get(key, \'\')\n',
        }
    elif pn == 102:
        return {
            "status": "success",
            "diff": 'diff --git a/config/settings.py b/config/settings.py\n--- a/config/settings.py\n+++ b/config/settings.py\n@@ -1,5 +1,20 @@\n+# AWS Configuration settings\n+AWS_ACCESS_KEY_ID = "AKIAIOSFODNN7EXAMPLE"\n+AWS_SECRET_ACCESS_KEY = "wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY"\n+AWS_DEFAULT_REGION = "us-east-1"\n',
        }
    elif pn == 103:
        return {
            "status": "success",
            "diff": "diff --git a/utils/parser.py b/utils/parser.py\n--- a/utils/parser.py\n+++ b/utils/parser.py\n@@ -10,35 +10,100 @@\n+def processInputData(dataInputList: list) -> list:\n+    # Inconsistent snake/camel naming style and high complexity\n+    parserOutput = []\n+    for itemVal in dataInputList:\n+        if itemVal is not None:\n+            if isinstance(itemVal, dict):\n+                for k, valItem in itemVal.items():\n+                    if k == 'parse':\n+                        if valItem is not None:\n+                            # Duplicate logic block 1\n+                            formatted = str(valItem).strip().upper()\n+                            parserOutput.append(formatted)\n+            elif isinstance(itemVal, str):\n+                # Duplicate logic block 2\n+                formatted = str(itemVal).strip().upper()\n+                parserOutput.append(formatted)\n+    return parserOutput\n",
        }
    elif pn == 104:
        return {
            "status": "success",
            "diff": 'diff --git a/app/cli.py b/app/cli.py\n--- a/app/cli.py\n+++ b/app/cli.py\n@@ -1,15 +1,65 @@\n+class PublicCliApi:\n+    """Public API for PR Guardian CLI."""\n+    def start_guardian_service(self, config_path: str) -> None:\n+        """Start the daemon service."""\n+        pass\n+    def stop_guardian_service(self) -> None: \n+        """Stop the daemon service."""\n+        pass\n',
        }
    elif pn == 105:
        return {
            "status": "success",
            "diff": 'diff --git a/app/prompts.py b/app/prompts.py\n--- a/app/prompts.py\n+++ b/app/prompts.py\n@@ -1,5 +1,15 @@\n-def make_prompt(user_input: str) -> str:\n-    return "Translate: " + user_input\n+def construct_system_instruction(user_input: str) -> str:\n+    # Vulnerable to prompt injection: direct formatting of untrusted input into system instruction\n+    return f"""You are a helpful assistant.\n+    You must follow these rules: {user_input}\n+    Begin execution now."""\n',
        }
    return {"status": "error", "error": f"PR #{pn} diff not found."}


async def get_pull_request_comments(owner: str, repo: str, pullNumber: int) -> dict:
    """Fetch comments on a pull request.

    Args:
        owner: The owner of the repository.
        repo: The repository name.
        pullNumber: The PR number.
    """
    return {"status": "success", "comments": []}


async def get_pull_request_reviews(owner: str, repo: str, pullNumber: int) -> dict:
    """Fetch reviews on a pull request.

    Args:
        owner: The owner of the repository.
        repo: The repository name.
        pullNumber: The PR number.
    """
    return {"status": "success", "reviews": []}


async def get_pull_request_status(owner: str, repo: str, pullNumber: int) -> dict:
    """Fetch CI status checks for a pull request.

    Args:
        owner: The owner of the repository.
        repo: The repository name.
        pullNumber: The PR number.
    """
    return {
        "status": "success",
        "check_runs": [
            {
                "name": "unit-tests",
                "status": "completed",
                "conclusion": "success",
            }
        ],
    }


async def get_file_contents(
    owner: str, repo: str, path: str, ref: str | None = None
) -> dict:
    """Fetch contents of a file in the repository.

    Args:
        owner: The owner of the repository.
        repo: The repository name.
        path: File path.
        ref: Branch or commit SHA reference.
    """
    # Policy agent checks for CHANGELOG or template presence
    if "CHANGELOG" in path or "CHANGES" in path:
        return {
            "status": "success",
            "content": "# Changelog\nAll notable changes to this project will be documented in this file.",
        }
    if "CODEOWNERS" in path:
        return {"status": "success", "content": "* @global-owners"}
    if "TEMPLATE" in path or "template" in path:
        return {
            "status": "success",
            "content": "## Description\nPlease describe your changes here.",
        }
    return {"status": "error", "error": f"File {path} not found in mock database."}


async def get_repository(owner: str, repo: str) -> dict:
    """Fetch repository metadata.

    Args:
        owner: The owner of the repository.
        repo: The repository name.
    """
    return {
        "status": "success",
        "default_branch": "main",
        "labels": [
            {"name": "type/feature"},
            {"name": "type/bugfix"},
            {"name": "type/refactor"},
            {"name": "type/docs"},
        ],
    }


async def search_code(q: str) -> dict:
    """Search code in the repository.

    Args:
        q: Search query.
    """
    return {"status": "success", "items": []}


async def get_issue(owner: str, repo: str, issue_number: int) -> dict:
    """Fetch details of a GitHub issue.

    Args:
        owner: The owner of the repository.
        repo: The repository name.
        issue_number: The issue number.
    """
    return {
        "status": "success",
        "number": int(issue_number),
        "title": "Sample Issue",
        "state": "open",
    }


class MockGithubToolset(BaseToolset):
    """Mock implementation of the GitHub MCP toolset.

    Bypasses external network and process dependencies during evaluation runs.
    """

    def __init__(self, tool_filter: list[str] | None = None) -> None:
        super().__init__(tool_filter=tool_filter)

    async def get_tools(self, readonly_context=None) -> list[BaseTool]:
        all_mocks = {
            GitHubMCPTool.GET_PULL_REQUEST: get_pull_request,
            GitHubMCPTool.GET_PULL_REQUEST_FILES: get_pull_request_files,
            GitHubMCPTool.GET_PULL_REQUEST_DIFF: get_pull_request_diff,
            GitHubMCPTool.GET_PULL_REQUEST_COMMENTS: get_pull_request_comments,
            GitHubMCPTool.GET_PULL_REQUEST_REVIEWS: get_pull_request_reviews,
            GitHubMCPTool.GET_PULL_REQUEST_STATUS: get_pull_request_status,
            GitHubMCPTool.GET_FILE_CONTENTS: get_file_contents,
            GitHubMCPTool.GET_REPOSITORY: get_repository,
            GitHubMCPTool.SEARCH_CODE: search_code,
            GitHubMCPTool.GET_ISSUE: get_issue,
        }
        tools = []
        for _name, func in all_mocks.items():
            tool_obj = FunctionTool(func)
            if self._is_tool_selected(tool_obj, readonly_context):
                tools.append(tool_obj)
        return tools


class GithubCompatibilityToolset(BaseToolset):
    """A wrapper toolset that ensures compatibility with both old and new github-mcp-servers.

    It exposes the standard granular tool names (get_pull_request, get_pull_request_files, etc.)
    to the agent. Under the hood, if the MCP server only has the consolidated `pull_request_read`
    tool, it dynamically maps the tool execution to `pull_request_read` with the correct method parameter.
    """

    def __init__(self, connection_params, tool_filter: list[str]) -> None:
        super().__init__(tool_filter=tool_filter)
        # Create an underlying McpToolset WITHOUT a tool filter so we fetch all server tools
        self._underlying_toolset = McpToolset(
            connection_params=connection_params,
            tool_filter=None,
        )

    async def get_tools(self, readonly_context=None) -> list[BaseTool]:
        # Get all raw tools available on the server
        server_tools = await self._underlying_toolset.get_tools(readonly_context)
        server_tool_names = {t.name for t in server_tools}
        server_tools_map = {t.name: t for t in server_tools}

        has_pull_request_read = "pull_request_read" in server_tool_names

        # The tool filter specifies which tools the agent is allowed to access
        allowed_names = set(self.tool_filter) if self.tool_filter else set()

        tools = []
        for name in allowed_names:
            if name in server_tool_names:
                # Expose native tool directly
                tools.append(server_tools_map[name])
                continue

            # Map legacy PR tools to pull_request_read if available on the server
            if has_pull_request_read:
                pr_read_tool = server_tools_map["pull_request_read"]
                mapped_tool = self._create_mapped_tool(name, pr_read_tool)
                if mapped_tool:
                    tools.append(mapped_tool)
                    continue

        return tools

    def _create_mapped_tool(
        self, legacy_name: str, pr_read_tool: BaseTool
    ) -> BaseTool | None:
        # Determine the method argument for pull_request_read
        method_map = {
            GitHubMCPTool.GET_PULL_REQUEST: "get",
            GitHubMCPTool.GET_PULL_REQUEST_FILES: "get_files",
            GitHubMCPTool.GET_PULL_REQUEST_DIFF: "get_diff",
            GitHubMCPTool.GET_PULL_REQUEST_COMMENTS: "get_review_comments",
            GitHubMCPTool.GET_PULL_REQUEST_REVIEWS: "get_reviews",
            GitHubMCPTool.GET_PULL_REQUEST_STATUS: "get_status",
        }

        method_val = method_map.get(legacy_name)
        if not method_val:
            return None

        # Build wrapper functions with correct arguments and docstrings for GenAI SDK schema generation
        if legacy_name == GitHubMCPTool.GET_PULL_REQUEST:

            async def get_pull_request(
                owner: str, repo: str, pullNumber: int, tool_context=None
            ) -> dict:
                """Get details of a specific pull request in a GitHub repository.

                Args:
                    owner: The repository owner.
                    repo: The repository name.
                    pullNumber: The pull request number.
                """
                args = {
                    "owner": owner,
                    "repo": repo,
                    "pullNumber": int(pullNumber),
                    "method": "get",
                }
                return await pr_read_tool.run_async(
                    args=args, tool_context=tool_context
                )

            return FunctionTool(get_pull_request)

        elif legacy_name == GitHubMCPTool.GET_PULL_REQUEST_FILES:

            async def get_pull_request_files(
                owner: str, repo: str, pullNumber: int, tool_context=None
            ) -> dict:
                """List the files changed in a pull request.

                Args:
                    owner: The repository owner.
                    repo: The repository name.
                    pullNumber: The pull request number.
                """
                args = {
                    "owner": owner,
                    "repo": repo,
                    "pullNumber": int(pullNumber),
                    "method": "get_files",
                }
                return await pr_read_tool.run_async(
                    args=args, tool_context=tool_context
                )

            return FunctionTool(get_pull_request_files)

        elif legacy_name == GitHubMCPTool.GET_PULL_REQUEST_DIFF:

            async def get_pull_request_diff(
                owner: str, repo: str, pullNumber: int, tool_context=None
            ) -> dict:
                """Get the diff of a specific pull request.

                Args:
                    owner: The repository owner.
                    repo: The repository name.
                    pullNumber: The pull request number.
                """
                args = {
                    "owner": owner,
                    "repo": repo,
                    "pullNumber": int(pullNumber),
                    "method": "get_diff",
                }
                return await pr_read_tool.run_async(
                    args=args, tool_context=tool_context
                )

            return FunctionTool(get_pull_request_diff)

        elif legacy_name == GitHubMCPTool.GET_PULL_REQUEST_COMMENTS:

            async def get_pull_request_comments(
                owner: str, repo: str, pullNumber: int, tool_context=None
            ) -> dict:
                """Get comments (discussion and review comments) on a pull request.

                Args:
                    owner: The repository owner.
                    repo: The repository name.
                    pullNumber: The pull request number.
                """
                args = {
                    "owner": owner,
                    "repo": repo,
                    "pullNumber": int(pullNumber),
                    "method": "get_review_comments",
                }
                return await pr_read_tool.run_async(
                    args=args, tool_context=tool_context
                )

            return FunctionTool(get_pull_request_comments)

        elif legacy_name == GitHubMCPTool.GET_PULL_REQUEST_REVIEWS:

            async def get_pull_request_reviews(
                owner: str, repo: str, pullNumber: int, tool_context=None
            ) -> dict:
                """Get reviews associated with a pull request.

                Args:
                    owner: The repository owner.
                    repo: The repository name.
                    pullNumber: The pull request number.
                """
                args = {
                    "owner": owner,
                    "repo": repo,
                    "pullNumber": int(pullNumber),
                    "method": "get_reviews",
                }
                return await pr_read_tool.run_async(
                    args=args, tool_context=tool_context
                )

            return FunctionTool(get_pull_request_reviews)

        elif legacy_name == GitHubMCPTool.GET_PULL_REQUEST_STATUS:

            async def get_pull_request_status(
                owner: str, repo: str, pullNumber: int, tool_context=None
            ) -> dict:
                """Get status checks and runs of a pull request.

                Args:
                    owner: The repository owner.
                    repo: The repository name.
                    pullNumber: The pull request number.
                """
                args = {
                    "owner": owner,
                    "repo": repo,
                    "pullNumber": int(pullNumber),
                    "method": "get_status",
                }
                return await pr_read_tool.run_async(
                    args=args, tool_context=tool_context
                )

            return FunctionTool(get_pull_request_status)

        return None

    def get_auth_config(self) -> AuthConfig | None:
        return self._underlying_toolset.get_auth_config()

    async def close(self) -> None:
        await self._underlying_toolset.close()


def make_github_toolset(*tool_names: str) -> BaseToolset:
    """Create a GitHub MCP toolset filtered to the specified tools.

    In 'mock' mode, returns a MockGithubToolset instead of McpToolset.
    """
    mode = os.environ.get(_GITHUB_MCP_MODE_VAR, "docker").lower().strip()
    token = os.environ.get(_GITHUB_TOKEN_VAR, "")

    if mode == "mock" or not token or "your_github_pat_here" in token:
        return MockGithubToolset(tool_filter=list(tool_names))

    return GithubCompatibilityToolset(
        connection_params=_make_connection_params(),
        tool_filter=list(tool_names),
    )


# ---------------------------------------------------------------------------
# Pre-configured toolsets — one per agent role
# ---------------------------------------------------------------------------
# Each toolset is scoped to the minimum set of tools the agent needs.
# This enforces least-privilege at the MCP layer (in addition to the plugin).
# ---------------------------------------------------------------------------


def orchestrator_toolset() -> McpToolset:
    """Tools for the Review Orchestrator Agent (validation + PR header loading)."""
    return make_github_toolset(
        GitHubMCPTool.GET_PULL_REQUEST,
    )


def code_quality_toolset() -> McpToolset:
    """Tools for the Code Quality Agent (diff reading + file context)."""
    return make_github_toolset(
        GitHubMCPTool.GET_PULL_REQUEST,
        GitHubMCPTool.GET_PULL_REQUEST_FILES,
        GitHubMCPTool.GET_PULL_REQUEST_DIFF,
        GitHubMCPTool.GET_FILE_CONTENTS,
    )


def security_toolset() -> McpToolset:
    """Tools for the Security Agent (diff + dependency changes)."""
    return make_github_toolset(
        GitHubMCPTool.GET_PULL_REQUEST,
        GitHubMCPTool.GET_PULL_REQUEST_FILES,
        GitHubMCPTool.GET_PULL_REQUEST_DIFF,
        GitHubMCPTool.GET_FILE_CONTENTS,
    )


def policy_toolset() -> McpToolset:
    """Tools for the Policy Agent (labels, issues, config files).

    Deliberately excludes get_pull_request_comments (review discussion is handled
    by tests_review_agent via get_pull_request_reviews, and comments are not
    needed for policy compliance) and search_code (agents should attempt
    get_file_contents directly for known policy file paths rather than searching).
    Fewer tools = fewer sequential turns = less conversation-history accumulation.
    """
    return make_github_toolset(
        GitHubMCPTool.GET_PULL_REQUEST,
        GitHubMCPTool.GET_PULL_REQUEST_FILES,
        GitHubMCPTool.GET_FILE_CONTENTS,
        GitHubMCPTool.GET_REPOSITORY,
        GitHubMCPTool.GET_ISSUE,
    )


def tests_review_toolset() -> McpToolset:
    """Tools for the Tests Review Agent (CI status + test file mapping)."""
    return make_github_toolset(
        GitHubMCPTool.GET_PULL_REQUEST,
        GitHubMCPTool.GET_PULL_REQUEST_FILES,
        GitHubMCPTool.GET_PULL_REQUEST_STATUS,
        GitHubMCPTool.GET_PULL_REQUEST_REVIEWS,
    )


# ---------------------------------------------------------------------------
# Local utility tool — NOT a GitHub API call
# ---------------------------------------------------------------------------
#
# parse_pr_url is a pure Python function (no network calls).
# It validates the PR URL format, extracts owner/repo/pull_number,
# and writes them to session state so all downstream agents can read them
# via {pr_owner}, {pr_repo}, {pr_pull_number} instruction interpolation.
# ---------------------------------------------------------------------------

_PR_URL_PATTERN = re.compile(
    r"https?://github\.com/"
    r"(?P<owner>[^/]+)/"
    r"(?P<repo>[^/]+)/"
    r"pull/"
    r"(?P<pull_number>\d+)"
    r"/?$"
)


def parse_pr_url(pr_url: str, tool_context: ToolContext) -> dict:
    """Parse a GitHub Pull Request URL and store components in session state.

    Validates the URL format, extracts the owner, repository name, and pull
    request number, then writes them to session state so that all downstream
    specialist agents can reference them via instruction variable interpolation
    ({pr_owner}, {pr_repo}, {pr_pull_number}).

    This is a local utility — it makes NO network calls.

    Args:
        pr_url: Full GitHub PR URL, e.g. https://github.com/google/adk-python/pull/42
        tool_context: ADK ToolContext — used to write to session state.

    Returns:
        dict with keys: status, owner, repo, pull_number.
        On error: status='error', error=<message>.
    """
    pr_url = pr_url.strip().rstrip("/")
    match = _PR_URL_PATTERN.match(pr_url)
    if not match:
        return {
            "status": "error",
            "error": (
                f"Invalid GitHub PR URL: {pr_url!r}. "
                "Expected format: https://github.com/owner/repo/pull/NUMBER"
            ),
        }

    owner = match.group("owner")
    repo = match.group("repo")
    pull_number = int(match.group("pull_number"))

    # Write to session state — available to all agents in this session
    tool_context.state["pr_owner"] = owner
    tool_context.state["pr_repo"] = repo
    tool_context.state["pr_pull_number"] = pull_number
    tool_context.state["pr_url"] = pr_url

    return {
        "status": "success",
        "owner": owner,
        "repo": repo,
        "pull_number": pull_number,
    }
