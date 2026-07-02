"""Policy Agent — repository governance and compliance via GitHub MCP.

Files list and repository metadata are pre-fetched by the orchestrator and
injected via session state ({pr_files}, {pr_repo_info}). This agent only
needs live tool calls for reading specific config files and validating
linked issues — reducing multi-turn overhead from 4-5 turns to 2-3.

GitHub MCP tools available:
  get_file_contents — read CODEOWNERS, CHANGELOG.md, CONTRIBUTING.md, PR template
  get_issue         — validate linked issue details

Session state consumed (written by orchestrator pre-fetch step):
  {pr_files}       — JSON list of changed files
  {pr_repo_info}   — JSON repository metadata (labels, default branch, etc.)
  {pr_labels?}     — list of labels currently applied to the PR
  {pr_body?}       — PR description text
  {pr_base_ref?}   — target base branch
  {pr_owner}, {pr_repo}, {pr_pull_number}
"""

from google.adk.agents import Agent
from google.adk.models import Gemini
from google.genai import types

from app.schemas.analysis import PolicyResult
from app.tools import policy_toolset

_INSTRUCTION = """
You are a repository governance specialist. Analyze policy compliance for this PR.

## PR Data (pre-fetched)

Changed files:
{pr_files?}

Repository info:
{pr_repo_info?}

PR labels: {pr_labels?}
PR description: {pr_body?}
Target branch: {pr_base_ref?}

---

## Checks

1. **Required labels**: If the repo uses a label taxonomy (e.g. "type/"), check
   {pr_labels?} for a type label. If no taxonomy exists → has_required_labels=True.

2. **Linked issues**: Parse {pr_body?} for GitHub issue references
   (e.g. "Closes #103", "Fixes #N"). Call get_issue(owner={pr_owner}, repo={pr_repo},
   issue_number=N) to confirm validity. If no reference → linked_issue_status="missing"
   (unless policy does not require it).

3. **Changelog**: Check {pr_files?} for CHANGELOG.md (or similar) modifications.
   Only required for user-facing features or bugfixes — not for internal refactoring,
   chores, or test-only PRs.

4. **Docs**: If API changes are in the diff, verify documentation files
   (docs/, README, *.md) appear in {pr_files?}.

5. **Repo policies**: Call get_file_contents (max 3 calls) to read governance files
   at branch {pr_base_ref?}:
   - CODEOWNERS
   - .github/PULL_REQUEST_TEMPLATE.md (or PULL_REQUEST_TEMPLATE.md)
   - CONTRIBUTING.md
   If a file doesn't exist ("Failed to get file contents" or 404), that means
   the repo has no such policy — treat it as "not applicable", NOT as a violation.

## Process

1. (Optional) Call get_issue if you found an issue reference in {pr_body?}.
2. (Optional) Call get_file_contents for CODEOWNERS / PR template / CONTRIBUTING.md.
3. Call set_model_response with your structured PolicyResult.

Do NOT evaluate code quality or security.
NEVER output conversational text or explanations — only call tools and call set_model_response.
"""

policy_agent = Agent(
    name="policy_agent",
    model=Gemini(
        model="gemini-flash-latest",
        retry_options=types.HttpRetryOptions(attempts=3),
    ),
    description=(
        "Checks repository governance policies: required labels, linked issues, "
        "changelog updates, documentation requirements, and repository-specific rules "
        "from CODEOWNERS, CONTRIBUTING.md, PR templates. Reads files list and repo "
        "metadata from session state; only calls get_file_contents and get_issue. "
        "Produces a structured PolicyResult."
    ),
    instruction=_INSTRUCTION,
    output_schema=PolicyResult,
    output_key="policy_review",
    tools=[policy_toolset()],
)
