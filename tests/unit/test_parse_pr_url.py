# Copyright 2026 Google LLC
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     https://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
"""Unit tests for parse_pr_url — the pure-Python PR URL parser.

parse_pr_url makes NO network calls and has no ADK dependencies beyond
ToolContext (which we stub here). These tests verify the regex parsing,
session state writes, and error handling in isolation.
"""

from __future__ import annotations

import os
import sys

# Force mock mode so imports don't try to connect to GitHub MCP
os.environ["GITHUB_MCP_MODE"] = "mock"
os.environ.setdefault("GOOGLE_GENAI_USE_VERTEXAI", "False")
os.environ.setdefault("GOOGLE_CLOUD_PROJECT", "test-project")

# Ensure the project root is on sys.path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))


class FakeState(dict):
    """Minimal ToolContext.state stub — just a dict with attribute-style access."""


class FakeToolContext:
    """Stub for google.adk.tools.ToolContext used in parse_pr_url."""

    def __init__(self) -> None:
        self.state: dict = FakeState()


# Import the function under test after env setup
from app.tools.mcp_tools import parse_pr_url  # noqa: E402

# ---------------------------------------------------------------------------
# Happy-path tests
# ---------------------------------------------------------------------------


def _ctx() -> FakeToolContext:
    """Helper — fresh tool context for each test."""
    return FakeToolContext()


def test_canonical_url_parses_correctly() -> None:
    """Standard https://github.com/owner/repo/pull/NUMBER URL should succeed."""
    ctx = _ctx()
    result = parse_pr_url("https://github.com/google/adk-python/pull/42", ctx)

    assert result["status"] == "success"
    assert result["owner"] == "google"
    assert result["repo"] == "adk-python"
    assert result["pull_number"] == 42


def test_session_state_is_written() -> None:
    """Session state keys must be populated for downstream agents."""
    ctx = _ctx()
    parse_pr_url("https://github.com/google/adk-python/pull/42", ctx)

    assert ctx.state["pr_owner"] == "google"
    assert ctx.state["pr_repo"] == "adk-python"
    assert ctx.state["pr_pull_number"] == 42
    assert "github.com" in ctx.state["pr_url"]


def test_trailing_slash_is_stripped() -> None:
    """Trailing slash in URL must be stripped before parsing."""
    ctx = _ctx()
    result = parse_pr_url("https://github.com/owner/repo/pull/99/", ctx)
    assert result["status"] == "success"
    assert result["pull_number"] == 99


def test_hyphenated_repo_name() -> None:
    """Repo names with hyphens are valid GitHub identifiers."""
    ctx = _ctx()
    result = parse_pr_url("https://github.com/my-org/my-awesome-repo/pull/1", ctx)
    assert result["status"] == "success"
    assert result["owner"] == "my-org"
    assert result["repo"] == "my-awesome-repo"


def test_large_pull_number() -> None:
    """Pull request numbers can be arbitrarily large."""
    ctx = _ctx()
    result = parse_pr_url("https://github.com/owner/repo/pull/99999", ctx)
    assert result["status"] == "success"
    assert result["pull_number"] == 99999


def test_whitespace_is_stripped() -> None:
    """Leading/trailing whitespace from copy-paste should be handled."""
    ctx = _ctx()
    result = parse_pr_url("  https://github.com/owner/repo/pull/7  ", ctx)
    assert result["status"] == "success"
    assert result["pull_number"] == 7


# ---------------------------------------------------------------------------
# Error-path tests
# ---------------------------------------------------------------------------


def test_missing_pull_number_returns_error() -> None:
    """URL without pull number should return an error, not raise."""
    ctx = _ctx()
    result = parse_pr_url("https://github.com/owner/repo", ctx)
    assert result["status"] == "error"
    assert "Invalid GitHub PR URL" in result["error"]


def test_non_github_url_returns_error() -> None:
    """Non-GitHub URLs must be rejected."""
    ctx = _ctx()
    result = parse_pr_url("https://gitlab.com/owner/repo/merge_requests/1", ctx)
    assert result["status"] == "error"


def test_empty_string_returns_error() -> None:
    """Empty input should return error gracefully."""
    ctx = _ctx()
    result = parse_pr_url("", ctx)
    assert result["status"] == "error"


def test_plain_text_returns_error() -> None:
    """Free text (not a URL) should return error."""
    ctx = _ctx()
    result = parse_pr_url("analyse the latest pull request please", ctx)
    assert result["status"] == "error"


def test_error_does_not_write_state() -> None:
    """On parse failure, session state should not be partially written."""
    ctx = _ctx()
    parse_pr_url("not-a-url", ctx)
    assert "pr_owner" not in ctx.state
    assert "pr_repo" not in ctx.state
    assert "pr_pull_number" not in ctx.state
