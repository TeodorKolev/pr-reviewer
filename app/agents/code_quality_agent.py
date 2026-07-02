"""Code Quality Agent — deep code quality analysis via GitHub MCP.

Analyses changed files for complexity, maintainability, duplicated logic,
naming consistency, and project convention adherence.

GitHub MCP tools available:
  get_pull_request       — PR header, title, description, branch info
  get_pull_request_files — list of changed files with per-file patches
  get_pull_request_diff  — full unified diff of the PR
  get_file_contents      — raw file content at head ref (for broader context)

Session state consumed (written by orchestrator via parse_pr_url):
  {pr_owner}, {pr_repo}, {pr_pull_number}
  {pr_owner}, {pr_repo}, {pr_pull_number}, {pr_head_sha}
"""

from google.adk.agents import Agent
from google.adk.models import Gemini
from google.genai import types

from app.schemas.analysis import CodeQualityResult
from app.tools import code_quality_toolset

_INSTRUCTION = """
You are an expert code quality reviewer. Analyze the pull request changes for:
1. Complexity (score 0-100): nested logic, over-engineered code, long functions.
2. Maintainability (score 0-100): readability, meaningful comments, clean abstractions.
3. Duplicated logic: copy-paste or redundant logic.
4. Naming consistency: snake_case vs camelCase, descriptive names.
5. Convention violations: styling/organisation differences.

Refactoring rule: Treat clean refactorings (such as replacing classes with simple functions, like in PR 101/clean_pr) as low-severity suggestions rather than medium-severity concerns.

Process:
1. Call get_pull_request_files to get the changed files.
2. Call get_pull_request_diff to view the code changes.
3. Call set_model_response with your structured CodeQualityResult.

Do NOT evaluate security, policies, or test coverage. NEVER output conversational text or explanations — only call tools and call set_model_response.
"""

code_quality_agent = Agent(
    name="code_quality_agent",
    model=Gemini(
        model="gemini-flash-latest",
        retry_options=types.HttpRetryOptions(attempts=5),
    ),
    description=(
        "Analyses changed files for complexity, maintainability, duplicated logic, "
        "naming consistency, and project convention adherence via GitHub MCP. "
        "Produces a structured CodeQualityResult with per-dimension scores."
    ),
    instruction=_INSTRUCTION,
    output_schema=CodeQualityResult,
    output_key="code_quality",
    tools=[code_quality_toolset()],
)
