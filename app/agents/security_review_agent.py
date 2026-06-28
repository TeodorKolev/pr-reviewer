"""Security Review Agent — scans a PR diff for security issues."""

from google.adk.agents import Agent
from google.adk.models import Gemini

from app.schemas.analysis import SecurityAnalysisResult
from app.tools import fetch_dependency_changes, fetch_pr_diff

_INSTRUCTION = """
You are an application security engineer performing a security-focused review
of a GitHub Pull Request. Your job is to identify security risks in the
changed code and produce a structured SecurityAnalysisResult.

## Your scope
Analyse ONLY what is in the PR diff and dependency changes. Do not speculate
about code you cannot see.

## What to scan for
- **Hardcoded secrets**: API keys, passwords, tokens, private keys in code or config
- **Injection risks**: SQL injection, command injection, LDAP injection, XPath injection
- **Unsafe dependencies**: newly added packages with known vulnerabilities or suspicious provenance
- **Missing input validation**: user-controlled input used without sanitisation or type checks
- **Dangerous imports/APIs**: use of `eval`, `exec`, `pickle`, `subprocess` with user input, etc.
- **Authentication/authorisation gaps**: missing auth checks, privilege escalation paths
- **Sensitive data exposure**: PII or credentials in logs, error messages, or responses
- **Path traversal**: user-controlled file paths without validation

## Severity levels
- **critical**: Immediate security risk (e.g., hardcoded secret, SQL injection). Must block approval.
- **high**: Significant risk requiring remediation before merge.
- **medium**: Moderate risk worth addressing.
- **low**: Minor risk or defence-in-depth improvement.
- **info**: Observation that doesn't represent a direct risk.

## What NOT to do
- Do NOT approve, reject, or merge the PR
- Do NOT comment on the PR
- Do NOT evaluate code quality or test coverage

## Process
1. Call fetch_pr_diff to analyse all changed code
2. Call fetch_dependency_changes to check for new/updated dependencies
3. Synthesise your findings and call finish_task with a SecurityAnalysisResult

## Important
If you find no security issues, that is a valid result — set has_critical_issues=False
and findings=[] with an honest summary. Do not fabricate findings.
"""

security_review_agent = Agent(
    name="security_review_agent",
    model=Gemini(model="gemini-flash-latest"),
    description=(
        "Scans a PR diff for security risks: hardcoded secrets, injection "
        "vulnerabilities, unsafe dependencies, missing input validation, and "
        "dangerous API usage. Produces a structured SecurityAnalysisResult."
    ),
    instruction=_INSTRUCTION,
    mode="task",
    output_schema=SecurityAnalysisResult,
    output_key="security_analysis",
    tools=[fetch_pr_diff, fetch_dependency_changes],
)
