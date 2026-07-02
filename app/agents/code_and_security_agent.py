"""Code & Security Agent — combined code quality and security analysis.

Replaces the separate code_quality_agent and security_agent. Both analyses
read the same diff, so one LLM call (after fetching) does the work of two.

Why this agent fetches its own diff instead of reading from state:
  If the orchestrator fetches the diff, it sits in the orchestrator's
  multi-turn conversation history for every turn that follows — multiplying
  its token cost (typically ~7,500 tokens) by 5-6x across formatting and
  delegation turns. By fetching here with include_contents="none", the diff
  is isolated in this agent's 2-turn context and never reaches the orchestrator.

Session state consumed (written by orchestrator pre-fetch step):
  {pr_owner?}, {pr_repo?}, {pr_pull_number?}  — PR coordinates
  {pr_files?}                                  — JSON list of changed files

Writes to state["code_and_security"] (CodeAndSecurityResult).
"""

from google.adk.agents import Agent
from google.adk.models import Gemini
from google.genai import types

from app.schemas.analysis import CodeAndSecurityResult
from app.tools import code_and_security_toolset

_INSTRUCTION = """
You are an expert code reviewer covering both code quality and security.

## Step 1 — Fetch the diff

Call:
  get_pull_request_diff(owner={pr_owner?}, repo={pr_repo?}, pullNumber={pr_pull_number?})

## Step 2 — Analyse

Using the diff from Step 1 and the changed files list below, produce a
CodeAndSecurityResult covering both dimensions.

Changed files (pre-fetched):
{pr_files?}

---

### Code Quality

Evaluate:
1. **Complexity** (complexity_score 0-100): deeply nested conditions, long functions.
   100 = simple and well-decomposed.
2. **Maintainability** (maintainability_score 0-100): readability, single-responsibility,
   clear abstractions.
3. **Duplicated logic**: copy-paste or near-duplicate blocks.
4. **Naming consistency**: snake_case vs camelCase mixing, non-descriptive identifiers.
5. **Convention violations**: style or structural differences from the surrounding codebase.

Rule: Clean refactorings (e.g. replacing a class with a simple function) are
low-severity suggestions, not medium concerns.

### Security

Evaluate:
1. **Secrets & credentials**: hardcoded API keys, tokens, passwords, private keys,
   database connection strings in source files or config.
2. **Dangerous patterns**: SQL injection, OS command injection, path traversal,
   unsafe deserialization (pickle, yaml.load), insecure crypto, eval/exec on user input.
3. **Dependency risks**: newly added packages in manifest files (pyproject.toml,
   package.json, requirements.txt, go.mod) with suspicious names or known vulnerabilities.
4. **Prompt injection**: user-controlled input concatenated directly into LLM prompts
   or system instructions without sanitization.

---

Do NOT evaluate policies or test coverage.
Call set_model_response with your complete CodeAndSecurityResult.
"""

code_and_security_agent = Agent(
    name="code_and_security_agent",
    model=Gemini(
        model="gemini-flash-latest",
        retry_options=types.HttpRetryOptions(attempts=3),
    ),
    description=(
        "Fetches the PR diff in its own isolated context (include_contents='none') "
        "and analyses it for code quality (complexity, maintainability, duplication, "
        "naming) and security (secrets, dangerous patterns, dependencies, prompt "
        "injection). Produces a structured CodeAndSecurityResult."
    ),
    instruction=_INSTRUCTION,
    include_contents="none",
    output_schema=CodeAndSecurityResult,
    output_key="code_and_security",
    tools=[code_and_security_toolset()],
)
