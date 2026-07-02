"""Tests Review Agent — CI status and test coverage analysis.

All data is pre-fetched by the orchestrator and written to session state.
This agent runs in single-turn mode with no tool calls.

Session state consumed:
  {pr_files}          — JSON list of changed files (source vs test correlation)
  {pr_ci_status}      — JSON list of CI check runs
  {pr_reviews}        — JSON list of PR review submissions
  {pr_mergeable_state?} — GitHub mergeable state string (CI proxy)

Writes to state["tests_analysis"] (TestsAnalysisResult).
"""

from google.adk.agents import Agent
from google.adk.models import Gemini
from google.genai import types

from app.schemas.analysis import TestsAnalysisResult

_INSTRUCTION = """
You are a quality engineer. Evaluate test coverage and CI results for this PR.

## PR Data (pre-fetched)

Changed files:
{pr_files?}

CI check runs:
{pr_ci_status?}

PR reviews:
{pr_reviews?}

PR mergeable state: {pr_mergeable_state?}

---

## CI Status (ci_passing)

- If check runs show all conclusions as "success" OR {pr_mergeable_state?} is "clean"
  → ci_passing = True
- If any check run conclusion is "failure" OR {pr_mergeable_state?} is "unstable"
  → ci_passing = False
- If no check runs exist and mergeable_state is absent or "unknown"
  → ci_passing = None

## Test Coverage

1. Identify which changed files are source files vs test files from {pr_files?}.
2. If functional source code was modified, check whether corresponding test files
   were also added or updated.
3. Assign test_quality_score:
   - 0   = no tests added for new/changed logic
   - 50-69 = happy path only
   - 70-89 = good edge cases covered
   - 90-100 = comprehensive tests with assertions and edge cases

Do NOT evaluate security or policy compliance.
Call set_model_response with your structured TestsAnalysisResult.
"""

tests_review_agent = Agent(
    name="tests_review_agent",
    model=Gemini(
        model="gemini-flash-latest",
        retry_options=types.HttpRetryOptions(attempts=3),
    ),
    description=(
        "Single-turn agent that evaluates CI check status and test coverage. "
        "Correlates source file changes with test file changes. "
        "Reads all data from session state — no tool calls. "
        "Produces a structured TestsAnalysisResult."
    ),
    instruction=_INSTRUCTION,
    mode="single_turn",
    include_contents="none",
    output_schema=TestsAnalysisResult,
    output_key="tests_analysis",
    tools=[],
)
