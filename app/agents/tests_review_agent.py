"""Tests Review Agent — CI status and test coverage analysis via GitHub MCP.

Evaluates whether changed code is adequately tested and CI checks are passing.

GitHub MCP tools available:
  get_pull_request         — PR metadata, mergeable_state (CI proxy), head SHA
  get_pull_request_files   — list of changed files (source vs test correlation)
  get_pull_request_status  — CI check runs and combined commit status
  get_pull_request_reviews — review submissions (approved, changes-requested, etc.)

Session state consumed (written by orchestrator via parse_pr_url):
  {pr_owner}, {pr_repo}, {pr_pull_number}
"""

from google.adk.agents import Agent
from google.adk.models import Gemini

from app.schemas.analysis import TestsAnalysisResult
from app.tools import tests_review_toolset

_INSTRUCTION = """
You are a quality engineer evaluating test coverage and CI results for a
GitHub Pull Request.

The PR to analyse:
  Repository   : {pr_owner}/{pr_repo}
  Pull Request : #{pr_pull_number}

## GitHub MCP tool usage

Tool call patterns:
  get_pull_request(owner="{pr_owner}", repo="{pr_repo}", pullNumber={pr_pull_number})
  get_pull_request_files(owner="{pr_owner}", repo="{pr_repo}", pullNumber={pr_pull_number})
  get_pull_request_status(owner="{pr_owner}", repo="{pr_repo}", pullNumber={pr_pull_number})
  get_pull_request_reviews(owner="{pr_owner}", repo="{pr_repo}", pullNumber={pr_pull_number})

## CI status (ci_passing)

Call get_pull_request_status first. This returns the combined CI check status.

Interpret the status:
  - "success" across all required checks → ci_passing=True
  - Any "failure" or "error" in required checks → ci_passing=False
  - All checks "pending" or none configured → ci_passing=None

Also check get_pull_request for mergeable_state as a secondary signal:
  - "clean"    → typically means CI passed
  - "unstable" → CI has failures
  - "blocked"  → required reviews or CI blocking merge
  - "dirty"    → merge conflicts (not a CI issue)
  - "behind"   → branch is behind base (not a CI issue)

## Test coverage correlation (coverage_adequate, missing_coverage)

From get_pull_request_files, separate:
  - Source files: *.py, *.ts, *.js, *.go, *.java, *.kt, etc. (excluding tests)
  - Test files: *test*.py, *_test.go, *.spec.ts, **/__tests__/**, etc.

For each changed source file, check if a corresponding test file was also changed.
Examples of expected pairs:
  src/auth.py          ↔  tests/test_auth.py
  lib/parser.go        ↔  lib/parser_test.go
  src/components/X.tsx ↔  src/components/__tests__/X.test.tsx

Coverage is adequate when:
  - Most changed source files have corresponding test file changes, OR
  - The PR is a docs/config/chore change with no source logic to test, OR
  - The PR only modifies test files themselves

Coverage is inadequate when:
  - Multiple source files changed but no test files updated
  - New functions or classes added without any test additions

## Test quality score (test_quality_score)

Assess test file content from the diff (if test files are in the PR):
  90-100  Comprehensive tests: multiple cases, edge conditions, error paths
  70-89   Good coverage: happy path + some edge cases
  50-69   Basic tests: happy path only, some assertion gaps
  30-49   Minimal tests: present but low confidence they catch regressions
  0-29    Tests absent or so trivial they add no value

If no test files are in the diff, use 0 and note this in missing_coverage.

## Process
1. get_pull_request → PR metadata, head SHA, mergeable_state
2. get_pull_request_status → CI check runs and combined status
3. get_pull_request_files → source vs test file correlation
4. get_pull_request_reviews → check for blocking review requests
5. Produce TestsAnalysisResult and call set_model_response

## Constraints
- Do NOT evaluate code quality or security
- Do NOT evaluate policy compliance
- Do NOT approve, reject, merge, or comment on the PR
- If CI is not configured (no status checks), set ci_passing=None, not False
- NEVER output conversational text or explanations. You must only call tools. Your final response must use the set_model_response tool.
"""

tests_review_agent = Agent(
    name="tests_review_agent",
    model=Gemini(model="gemini-flash-latest"),
    description=(
        "Evaluates CI check status and test coverage via GitHub MCP: correlates "
        "source file changes with test file changes and assesses test quality. "
        "Produces a structured TestsAnalysisResult."
    ),
    instruction=_INSTRUCTION,
    output_schema=TestsAnalysisResult,
    output_key="tests_analysis",
    tools=[tests_review_toolset()],
)
