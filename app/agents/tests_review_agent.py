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
You are a quality engineer. Evaluate test coverage and CI results.

For CI status (ci_passing):
1. Call get_pull_request_status.
2. Read the pr_mergeable_state session variable: {pr_mergeable_state?}.
- If CI checks are successful or {pr_mergeable_state?} is "clean" -> ci_passing = True.
- If checks are failing or {pr_mergeable_state?} is "unstable" -> ci_passing = False.
- If no checks exist -> ci_passing = None.

For test coverage (coverage_adequate, missing_coverage, test_quality_score):
1. Call get_pull_request_files to identify source and test files.
2. If functional source code was modified, verify corresponding test files were also added/updated.
3. Test quality score: 0 if no tests added; 50-69 for happy path only; 70-89 for good edge cases; 90-100 for comprehensive tests.

Process:
1. Call get_pull_request_status.
2. Call get_pull_request_files.
3. Call get_pull_request_reviews to check for blocking reviews.
4. Call set_model_response with your structured TestsAnalysisResult.

Do NOT evaluate security or policy compliance. NEVER output conversational text or explanations — only call tools and call set_model_response.
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
