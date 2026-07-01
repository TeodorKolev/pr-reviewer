"""Security Agent — security analysis via GitHub MCP.

Analyses ONLY the changed code for:
  - Exposed secrets and credentials
  - Dangerous code patterns (injection, path traversal, eval, etc.)
  - Dependency risks (newly added packages with known vulnerabilities)
  - AI/LLM-specific prompt injection vulnerabilities

GitHub MCP tools available:
  get_pull_request       — PR header and metadata
  get_pull_request_files — list of changed files with per-file patches (incl. dep manifests)
  get_pull_request_diff  — full unified diff
  get_file_contents      — read full content of changed dependency manifest files

Session state consumed (written by orchestrator via parse_pr_url):
  {pr_owner}, {pr_repo}, {pr_pull_number}
"""

from google.adk.agents import Agent
from google.adk.models import Gemini

from app.schemas.analysis import SecurityResult
from app.tools import security_toolset

_INSTRUCTION = """
You are an application security engineer. Analyze the pull request changes for:
1. Secrets & credentials: hardcoded API keys, tokens, passwords, database credentials.
2. Dangerous patterns: SQL injection, command injection, path traversal, unsafe deserialization (pickle, yaml), insecure crypto.
3. Dependency risks: newly added packages with potential vulnerabilities or typosquatting names in manifest files (pyproject.toml, package.json, requirements.txt, go.mod).
4. Prompt injection: user input concatenated directly into LLM prompts without sanitization.

To inspect changed dependency manifests, call get_file_contents for the manifest path at base branch using the head SHA: {pr_head_sha?}.

Process:
1. Call get_pull_request_files to get the changed files list.
2. Call get_pull_request_diff to get the code changes.
3. Call get_file_contents (optional, max 1) if a dependency manifest was modified.
4. Call set_model_response with your structured SecurityResult.

Do NOT evaluate code quality, policies, or tests. NEVER output conversational text or explanations — only call tools and call set_model_response.
"""

security_agent = Agent(
    name="security_agent",
    model=Gemini(model="gemini-flash-latest"),
    description=(
        "Analyses changed code for exposed secrets, dangerous patterns, "
        "dependency risks, and AI/LLM prompt injection vulnerabilities "
        "via GitHub MCP. Produces a structured SecurityResult."
    ),
    instruction=_INSTRUCTION,
    output_schema=SecurityResult,
    output_key="security_review",
    tools=[security_toolset()],
)
