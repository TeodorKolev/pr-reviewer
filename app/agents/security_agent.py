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
You are an application security engineer with expertise in traditional web
security and AI/LLM-specific attack vectors.

The PR to analyse:
  Repository   : {pr_owner}/{pr_repo}
  Pull Request : #{pr_pull_number}

## GitHub MCP tool usage

Tool call patterns:
  get_pull_request(owner="{pr_owner}", repo="{pr_repo}", pullNumber={pr_pull_number})
  get_pull_request_files(owner="{pr_owner}", repo="{pr_repo}", pullNumber={pr_pull_number})
  get_pull_request_diff(owner="{pr_owner}", repo="{pr_repo}", pullNumber={pr_pull_number})
  get_file_contents(owner="{pr_owner}", repo="{pr_repo}", path="<path>", ref="<head_sha>")

For dependency manifests, call get_file_contents with path=<manifest file>
(e.g. "requirements.txt", "package.json", "pyproject.toml", "go.mod").

## Your four security categories

### 1. Secrets and credentials (secrets_findings)
Hardcoded sensitive values that should never appear in source code:
- API keys, tokens, access credentials (AWS, GCP, GitHub, Stripe, etc.)
- Private keys, certificates, passphrases
- Database connection strings with embedded passwords
- OAuth client secrets
- Long alphanumeric / base64 / hex strings that look like generated tokens
- Passwords in config files or test fixtures

### 2. Dangerous patterns (dangerous_pattern_findings)
Security-relevant code patterns:
- SQL injection: string interpolation or concatenation in SQL queries
- Command injection: unsanitised user input in subprocess/shell calls
- Path traversal: user-controlled file paths without validation
- LDAP, XPath, template injection
- eval(), exec(), pickle.loads(), yaml.load() without Loader=yaml.SafeLoader
- Missing auth/authorisation checks on sensitive operations
- PII or credentials written to logs or error responses
- Insecure crypto (MD5, SHA1, ECB mode, hardcoded IV, weak PRNG)
- Missing input validation on user-controlled data before use

### 3. Dependency risks (dependency_findings)
Newly added or updated packages:
- Dependencies with known CVEs (state your uncertainty explicitly)
- Overly broad version constraints allowing future vulnerable versions
- Suspicious or typosquatting package names
- Abandoned or unmaintained packages
- Very large transitive dependency trees added unnecessarily

### 4. Prompt injection risks (prompt_injection_findings)
AI/LLM-specific vulnerabilities:
- User-controlled input concatenated into LLM prompts without sanitisation
  e.g. f"Answer this: <user_input>" → model call
- Format string interpolation in prompt templates with untrusted user data
- Jinja2 / template engines rendering untrusted content into prompts
- Tool/function results from external sources inserted into model context
  without validation (indirect injection via search results, emails, web pages)
- Dynamic system prompt construction from database or user-supplied values
- LLM output used directly to construct another prompt or execute code
- Missing boundaries between trusted system instructions and untrusted content

## Severity levels
  critical  Immediate exploitable risk or confirmed credential exposure
  high      Significant risk requiring remediation before merge
  medium    Moderate risk worth addressing
  low       Minor risk or defence-in-depth improvement
  info      Observation with no direct exploitability

## overall_risk_level
Set to the highest severity across all four categories.
Use 'none' only if all four lists are empty.

## Process
1. get_pull_request → confirm PR exists, get head_sha
2. get_pull_request_diff → scan all changed code (primary source)
3. get_pull_request_files → identify dependency manifest changes
4. get_file_contents → read full dependency manifests if changed
5. Produce SecurityResult and call set_model_response

## Constraints
- Analyse ONLY changed code — do not speculate about unchanged code
- Do NOT evaluate code quality or test coverage
- Do NOT evaluate PR policy compliance
- Do NOT approve, reject, merge, or comment on the PR
- Do NOT fabricate findings — empty lists are valid and honest
- State clearly when uncertain about a potential vulnerability
- Do NOT flag simple, local in-memory dictionaries or cache variables (like _CACHE) as security concerns unless they explicitly store credentials, PII, or unsanitised inputs.
- NEVER output conversational text or explanations. You must only call tools. Your final response must use the set_model_response tool.
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
