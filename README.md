# PR Guardian 🛡️

> **AI-powered Pull Request analysis agent — advisory-only, human-in-the-loop, read-only.**

PR Guardian is a multi-agent system built on [Google ADK 2.0](https://adk.dev) that analyses GitHub Pull Requests across four dimensions simultaneously — **code quality**, **security**, **repository policy**, and **test coverage** — and produces a structured recommendation for the human reviewer.

It never approves, rejects, merges, or comments on a PR. It only advises.

---

## The Problem

Code review is one of the most important quality gates in software engineering, yet:

- **It is inconsistent.** Different reviewers catch different things, and fatigue causes misses.
- **It is a security gap.** Secrets, injections, and unsafe dependencies slip through when reviewers focus on logic.
- **It does not scale.** Senior engineers become review bottlenecks on fast-moving teams.
- **Context is lost.** Reviewers rarely check linked issues, changelog requirements, CI status, and code quality simultaneously.

A single LLM cannot solve this well — a 1000-line diff with 10 changed files overwhelms a single context window, and security review requires a fundamentally different lens than code style review.

**The right tool is a specialist multi-agent pipeline.**

---

## The Solution

PR Guardian runs **four specialist AI agents in parallel**, each focused on a single analysis dimension, then **synthesizes** their structured outputs into a single recommendation with confidence score.

```
User: "Analyse https://github.com/owner/repo/pull/42"
           │
           ▼
┌─────────────────────────────────────────────────────┐
│           review_orchestrator_agent                 │
│  Parse URL → Fetch PR via GitHub MCP → Delegate    │
└────────────────────┬────────────────────────────────┘
                     │
                     ▼
        ┌────────────────────────┐
        │  analysis_pipeline     │
        │  (SequentialAgent)     │
        └────────────┬───────────┘
                     │
         ┌───────────▼────────────┐
         │   specialist_panel     │
         │   (ParallelAgent)      │
         │  ┌──────────────────┐  │
         │  │ code_quality     │──┼──▶ state["code_quality"]
         │  │ security         │──┼──▶ state["security_review"]
         │  │ policy           │──┼──▶ state["policy_review"]
         │  │ tests_review     │──┼──▶ state["tests_analysis"]
         │  └──────────────────┘  │
         └───────────┬────────────┘
                     │
                     ▼
         ┌───────────────────────┐
         │   synthesizer_agent   │──▶ PRRecommendation (JSON + human report)
         └───────────────────────┘
```

### Why Agents?

| Challenge | Why Agents Help |
|---|---|
| Multiple analysis dimensions | ParallelAgent runs all four simultaneously — no sequential bottleneck |
| Structured, typed outputs | Each agent uses a Pydantic `output_schema` — no free-text parsing needed |
| Long diffs | Each specialist focuses on one dimension — smaller, focused context windows |
| Tool safety | ADK plugins enforce read-only MCP access at the framework level |
| Evaluation | ADK's eval framework lets us verify agent behavior with reproducible test cases |

---

## Agent Architecture

### Agents

| Agent | Type | Role |
|---|---|---|
| `review_orchestrator_agent` | `Agent` | Entry point. Validates PR URL, fetches header, delegates to pipeline |
| `specialist_panel` | `ParallelAgent` | Runs all four specialists concurrently |
| `code_quality_agent` | `Agent` | Code complexity, duplication, naming, maintainability |
| `security_agent` | `Agent` | Secrets, dangerous patterns, dependency risks, prompt injection |
| `policy_agent` | `Agent` | Labels, linked issues, changelog, CODEOWNERS, CONTRIBUTING.md |
| `tests_review_agent` | `Agent` | CI status, test coverage gaps, test quality |
| `analysis_pipeline` | `SequentialAgent` | Sequences the panel then the synthesizer |
| `synthesizer_agent` | `Agent` | Aggregates all structured results into `PRRecommendation` |

### Tools — GitHub MCP (only external integration)

All GitHub data access goes through the [GitHub MCP Server](https://github.com/github/github-mcp-server). No agent makes direct REST or GraphQL calls.

| MCP Tool | Used by | Purpose |
|---|---|---|
| `get_pull_request` | Orchestrator, all specialists | PR metadata, title, author, head/base, draft status |
| `get_pull_request_files` | Code quality, security, policy | List of changed files with per-file patches |
| `get_pull_request_diff` | Code quality, security | Full unified diff |
| `get_pull_request_comments` | Policy | Review discussion and inline annotations |
| `get_pull_request_reviews` | Policy | Review submissions (approved, changes-requested) |
| `get_pull_request_status` | Tests review | CI check runs and combined commit status |
| `get_file_contents` | Security, policy | Raw file content (dependency manifests, CODEOWNERS, etc.) |
| `get_repository` | Policy | Repository metadata, label list, default branch |
| `search_code` | Policy | Search for policy files within the repo |
| `get_issue` | Policy | Validate linked issue details |

**Compatibility note**: `GithubCompatibilityToolset` automatically handles the GitHub MCP API change in v0.18+ (where granular PR tools were consolidated into `pull_request_read`). The compatibility layer dynamically maps legacy tool names to the new unified API, so agents work identically against any server version.

### Structured Output Schemas

All inter-agent communication uses typed Pydantic models defined in `app/schemas/`:

```python
PRRecommendation
  ├── recommendation: "Ready for Approval" | "Needs Minor Changes"
  │                 | "Request Changes" | "Manual Investigation Recommended"
  ├── recommendation_reason: str        # Detailed why-this-recommendation explanation
  ├── confidence: "high" | "medium" | "low"
  ├── summary: str                      # 3–5 sentence narrative
  ├── security_findings: list[SecurityFinding]
  ├── code_quality_findings: list[Concern]
  ├── policy_findings: list[PolicyViolation]
  ├── suggestions: list[Issue]          # Non-blocking improvements
  ├── human_approval_required: bool     # Always True
  └── disclaimer: str                   # Advisory-only statement (always included)
```

---

## Security Model

PR Guardian is **read-only and advisory by design**. This is enforced at multiple layers:

### 1. Prompt-level enforcement
Every agent instruction contains explicit constraints:
> *"You NEVER approve, reject, merge, or comment on a Pull Request. The final decision ALWAYS belongs to the human reviewer."*

### 2. `ReadOnlyEnforcerPlugin` — hard runtime guardrail

An ADK `BasePlugin` intercepts **every tool call** via `before_tool_callback` before execution. It applies two independent checks:

- **Allowlist check**: The tool name must be in `GitHubMCPTool.ALL_READ_ONLY`. Unknown tools are blocked (fail-closed).
- **Write-prefix safeguard**: Tool names starting with `create_`, `update_`, `delete_`, `merge_`, `close_`, `add_`, `push_`, `fork_`, etc., are unconditionally blocked.

```python
# The plugin never throws — it returns a clear error dict the LLM sees
{
    "status": "error",
    "error": "SAFETY VIOLATION: PR Guardian is read-only and advisory. The attempted operation was blocked."
}
```

This is a **hard runtime guardrail** — it fires even if the LLM were somehow convinced to attempt a write operation, making the system safe regardless of prompt manipulation.

### 3. Prompt injection detection

The `security_agent` explicitly scans for AI/LLM-specific vulnerabilities:
- User-controlled input concatenated into LLM prompts without sanitisation
- Format string injection in prompt templates
- Indirect injection via external data sources inserted into model context

---

## Human-in-the-Loop Approval Model

PR Guardian always ends with one of four advisory recommendations:

| Recommendation | Trigger Conditions |
|---|---|
| **Ready for Approval** | No blocking issues, CI passing, code quality ≥ 80, policy compliant |
| **Needs Minor Changes** | Minor quality/style issues, non-blocking policy warnings |
| **Request Changes** | Critical security findings, CI failing, blocking policy violations |
| **Manual Investigation Recommended** | Low confidence — massive diff, missing CI results, ambiguous context |

Every report includes:
- A **detailed recommendation reason** explaining exactly why this recommendation was chosen
- A **confidence score** (high / medium / low)
- A mandatory **advisory disclaimer** in both the human-readable report and the JSON schema
- `human_approval_required: true` in the JSON output (always, enforced by schema default)

---

## Evaluation Framework

PR Guardian ships with a reproducible evaluation suite covering 5 representative PR scenarios:

| Scenario | Expected Recommendation | What's Tested |
|---|---|---|
| `clean_pr` | Ready for Approval | Correct handling of a well-formed, tested PR |
| `security_issue` | Request Changes | Hardcoded AWS credentials detection |
| `poor_code_quality` | Needs Minor Changes | Naming violations, high complexity, missing tests |
| `missing_documentation` | Needs Minor Changes | Missing labels, no linked issue, no changelog |
| `prompt_injection_attempt` | Request Changes | User input formatted directly into LLM prompt |

```bash
# Run the full evaluation suite (mock mode — no GitHub token required)
uv run python tests/eval/run_eval.py
```

Expected output: `🎉 ALL EVALUATION CASES PASSED SUCCESSFULLY!`

---

## Prerequisites

- [uv](https://docs.astral.sh/uv/getting-started/installation/) — Python package manager
- [agents-cli](https://github.com/google/agents-cli) — `uv tool install google-agents-cli`
- [Docker Desktop](https://www.docker.com/products/docker-desktop/) — for GitHub MCP server (default mode)
- A [GitHub Personal Access Token](https://github.com/settings/tokens) with `repo` scope
- A Google Cloud project (for Vertex AI / production deployment)

---

## Setup

### 1. Install dependencies

```bash
git clone https://github.com/your-org/pr-reviewer
cd pr-reviewer
agents-cli install
```

### 2. Configure environment

Create `app/.env` from the template:

```bash
# Required — your GitHub Personal Access Token
GITHUB_TOKEN=ghp_your_token_here

# Required for Vertex AI (production)
GOOGLE_CLOUD_PROJECT=your-gcp-project-id
GOOGLE_GENAI_USE_VERTEXAI=True

# Optional — Gemini API key for local dev without Vertex AI
GOOGLE_API_KEY=your_gemini_api_key_here

# MCP connection mode: docker (default) | binary | sse | http
GITHUB_MCP_MODE=docker
```

> ⚠️ **Never commit this file.** `app/.env` is gitignored.

### 3. Pull the GitHub MCP server image (docker mode)

```bash
docker pull ghcr.io/github/github-mcp-server
```

**Alternative — binary mode:**

Download `github-mcp-server` from [releases](https://github.com/github/github-mcp-server/releases) and set:
```bash
GITHUB_MCP_MODE=binary
GITHUB_MCP_BINARY=/path/to/github-mcp-server
```

**Alternative — mock mode** (no GitHub token needed, for development and evaluation):
```bash
GITHUB_MCP_MODE=mock
```

---

## Usage

### Interactive playground

```bash
agents-cli playground
```

Then type:
```
Analyse this PR: https://github.com/google/adk-python/pull/42
```

### A2A protocol endpoint

The agent exposes an [A2A protocol](https://a2a-protocol.org) HTTP endpoint:

```bash
curl -X POST http://localhost:8000/run \
  -H "Content-Type: application/json" \
  -d '{"message": {"parts": [{"text": "Analyse https://github.com/google/adk-python/pull/42"}]}}'
```

### Run evaluation (no token needed)

```bash
GITHUB_MCP_MODE=mock uv run python tests/eval/run_eval.py
```

---

## Project Structure

```
pr-reviewer/
├── app/
│   ├── agent.py                           # ADK App entry point — root agent + plugins
│   ├── agents/
│   │   ├── review_orchestrator_agent.py   # Root agent — validates URL, orchestrates pipeline
│   │   ├── code_quality_agent.py          # Code complexity, duplication, naming
│   │   ├── security_agent.py              # Secrets, injections, dependencies, prompt injection
│   │   ├── policy_agent.py                # Labels, issues, changelog, CODEOWNERS
│   │   ├── tests_review_agent.py          # CI status, coverage gaps
│   │   └── synthesizer_agent.py           # Aggregates all outputs → PRRecommendation
│   ├── tools/
│   │   └── mcp_tools.py                   # GitHub MCP integration + compatibility layer
│   ├── plugins/
│   │   └── readonly_enforcer.py           # Hard runtime safety guardrail (BasePlugin)
│   ├── schemas/
│   │   ├── analysis.py                    # Specialist output schemas (Pydantic)
│   │   └── recommendation.py             # PRRecommendation final output schema
│   └── fast_api_app.py                    # FastAPI / A2A protocol endpoint
├── tests/
│   ├── eval/
│   │   ├── datasets/                      # 5 mock PR evaluation scenarios (JSON)
│   │   ├── run_eval.py                    # Local evaluation runner
│   │   └── eval_config.yaml              # ADK eval configuration
│   ├── unit/                              # Unit tests
│   ├── integration/                       # Integration tests
│   └── load_test/                         # Load tests
├── deployment/
│   └── terraform/                         # Cloud Run + IAM + Secret Manager infrastructure
├── .github/workflows/                     # CI/CD — test, lint, deploy pipelines
├── Dockerfile                             # Container image for Cloud Run
├── agents-cli-manifest.yaml              # agents-cli project configuration
└── pyproject.toml                         # Dependencies (uv)
```

---

## Development Commands

| Command | Description |
|---|---|
| `agents-cli install` | Install all dependencies |
| `agents-cli playground` | Launch local development UI with hot-reload |
| `agents-cli lint` | Run ruff, codespell, and ty type checker |
| `uv run python tests/eval/run_eval.py` | Run evaluation suite (mock mode) |
| `uv run pytest tests/unit tests/integration` | Run unit and integration tests |
| `agents-cli eval` | Run ADK evaluation framework |

---

## Deployment

### Cloud Run (one command)

```bash
gcloud config set project YOUR_PROJECT_ID
agents-cli deploy
```

### Infrastructure setup

```bash
# Set up Cloud Run + IAM + Secret Manager
agents-cli infra single-project

# Set up full CI/CD pipeline with GitHub Actions
agents-cli infra cicd
```

### Production environment variables

Set these in GCP Secret Manager (Terraform provisions access automatically):

| Variable | Description |
|---|---|
| `GITHUB_TOKEN` | GitHub PAT with `repo` scope |
| `GITHUB_MCP_MODE` | `sse` or `http` for hosted MCP server |
| `GITHUB_MCP_URL` | URL of your hosted MCP server |
| `GOOGLE_CLOUD_PROJECT` | Your GCP project ID |

### Observability

Built-in telemetry exports to:
- **Cloud Trace** — agent execution traces with tool call spans
- **BigQuery** — structured evaluation logs and recommendation history  
- **Cloud Logging** — safety violation alerts from `ReadOnlyEnforcerPlugin`

---

## Technology Stack

| Technology | Role |
|---|---|
| [Google ADK 2.0](https://adk.dev) | Multi-agent framework (Agent, ParallelAgent, SequentialAgent, App) |
| [GitHub MCP Server](https://github.com/github/github-mcp-server) | Sole external integration for all GitHub data |
| [Gemini Flash](https://ai.google.dev/gemini-api/docs/models) | LLM backbone for all agents |
| [agents-cli](https://github.com/google/agents-cli) | Project scaffolding, linting, eval, deployment |
| [Pydantic](https://docs.pydantic.dev/) | Typed inter-agent schemas |
| [FastAPI](https://fastapi.tiangolo.com/) | A2A protocol HTTP endpoint |
| [Cloud Run](https://cloud.google.com/run) | Serverless deployment target |
| [Terraform](https://www.terraform.io/) | Infrastructure as code |
| [uv](https://docs.astral.sh/uv/) | Python dependency management |

---

## Built With Antigravity

This project was designed and built using [Google Antigravity (AGY)](https://antigravity.dev) — the AI-assisted development environment — with [agents-cli](https://github.com/google/agents-cli) for the full ADK project lifecycle (scaffold, lint, eval, deploy).

---

## License

Apache 2.0 — see [LICENSE](LICENSE).
