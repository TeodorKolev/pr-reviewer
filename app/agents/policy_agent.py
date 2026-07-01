"""Policy Agent — repository governance and compliance via GitHub MCP.

Checks repository contribution policies:
  - Required labels presence
  - Linked issues
  - Changelog / release notes updates
  - Documentation requirements
  - Repository-specific rules (CODEOWNERS, PR templates, CONTRIBUTING.md)

GitHub MCP tools available:
  get_pull_request       — PR metadata, labels, description, head branch
  get_pull_request_files — list of changed files (to check changelog/docs)
  get_file_contents      — read CODEOWNERS, CHANGELOG.md, CONTRIBUTING.md, PR template
  get_repository         — repo metadata, default branch, label list
  get_issue              — validate linked issue details

Session state consumed (written by orchestrator via parse_pr_url):
  {pr_owner}, {pr_repo}, {pr_pull_number}
"""

from google.adk.agents import Agent
from google.adk.models import Gemini

from app.schemas.analysis import PolicyResult
from app.tools import policy_toolset

_INSTRUCTION = """
You are a repository governance specialist. Analyze policy compliance for the PR.

PR metadata from session state:
- Labels: {pr_labels?}
- Description: {pr_body?}
- Target base branch: {pr_base_ref?}

Checks:
1. Required labels: If labels use taxonomy (e.g., "type/"), ensure a type label is present. Otherwise, has_required_labels=True.
2. Linked issues: Parse the description {pr_body?} for GitHub issue references (e.g. "Closes #103", "Fixes #N"). Call get_issue(issue_number=N) to confirm it is valid.
3. Changelog: Verify if CHANGELOG.md (or similar) is updated. An update is only required for user-facing features or bugfixes, not for internal refactoring, chores, or test-only PRs (like clean_pr).
4. Docs: If API changes are present, verify documentation is updated.
5. Repo policies: Call get_file_contents for CODEOWNERS, PULL_REQUEST_TEMPLATE.md, or CONTRIBUTING.md at branch {pr_base_ref?}. List any violations.

Process:
1. Call get_pull_request_files.
2. Call get_repository to get all repo labels and settings.
3. Call get_file_contents (max 3) for policies like CODEOWNERS or CHANGELOG base branch files.
4. Call get_issue (optional) if an issue reference was parsed in description.
5. Call set_model_response with your structured PolicyResult.

Do NOT evaluate code quality or security. NEVER output conversational text or explanations — only call tools and call set_model_response.
"""

policy_agent = Agent(
    name="policy_agent",
    model=Gemini(model="gemini-flash-latest"),
    description=(
        "Checks repository governance policies via GitHub MCP: required labels, "
        "linked issues, changelog updates, documentation requirements, and "
        "repository-specific rules from CODEOWNERS, CONTRIBUTING.md, PR templates. "
        "Produces a structured PolicyResult."
    ),
    instruction=_INSTRUCTION,
    output_schema=PolicyResult,
    output_key="policy_review",
    tools=[policy_toolset()],
)
