"""Review Orchestrator Agent — entry point and coordinator for PR Guardian.

Receives a GitHub Pull Request URL, validates it, pre-fetches ALL PR data in
one step (writing it to session state), then orchestrates the specialist panel.

Session state written by this agent:
  Via parse_pr_url:
    pr_owner, pr_repo, pr_pull_number, pr_url

  Via pre-fetch tool calls (through CachedTool state hooks):
    pr_title, pr_body, pr_base_ref, pr_head_ref, pr_head_sha,
    pr_mergeable_state, pr_labels  ← from get_pull_request
    pr_files                        ← from get_pull_request_files (JSON string)
    pr_ci_status                    ← from get_pull_request_status (JSON string)
    pr_reviews                      ← from get_pull_request_reviews (JSON string)
    pr_repo_info                    ← from get_repository (JSON string)

  NOT fetched here (to avoid diff accumulating across orchestrator turns):
    pr_diff  ← fetched by code_and_security_agent in its own isolated context

These state keys are read by specialist agents via instruction interpolation.
Specialist agents are single-turn and make no tool calls themselves (except
policy_agent which may call get_file_contents and get_issue).

Agent topology:
  review_orchestrator_agent
    │── parse_pr_url           (local Python tool — sets session state)
    │── get_pull_request       (validates PR + writes pr_* metadata to state)
    │── get_pull_request_files (writes pr_files to state)
    │── get_pull_request_diff  (writes pr_diff to state)
    │── get_pull_request_status (writes pr_ci_status to state)
    │── get_pull_request_reviews (writes pr_reviews to state)
    │── get_repository         (writes pr_repo_info to state)
    └── analysis_pipeline      (SequentialAgent)
          ├── specialist_panel (ParallelAgent)
          │     ├── code_and_security_agent → state["code_and_security"]
          │     ├── policy_agent            → state["policy_review"]
          │     └── tests_review_agent      → state["tests_analysis"]
          └── synthesizer_agent             → state["pr_recommendation"]
"""

from google.adk.agents import Agent, ParallelAgent, SequentialAgent
from google.adk.models import Gemini
from google.genai import types

from app.agents.code_and_security_agent import code_and_security_agent
from app.agents.policy_agent import policy_agent
from app.agents.synthesizer_agent import synthesizer_agent
from app.agents.tests_review_agent import tests_review_agent
from app.tools import orchestrator_toolset, parse_pr_url

# ---------------------------------------------------------------------------
# Pipeline: parallel fan-out → synthesizer fan-in
# ---------------------------------------------------------------------------

specialist_panel = ParallelAgent(
    name="specialist_panel",
    description=(
        "Runs three specialist agents concurrently. code_and_security_agent and "
        "tests_review_agent are single-turn and read from session state. "
        "policy_agent may call get_file_contents / get_issue. "
        "Each writes a structured JSON result to its own session state key."
    ),
    sub_agents=[
        code_and_security_agent,  # → state["code_and_security"]
        policy_agent,             # → state["policy_review"]
        tests_review_agent,       # → state["tests_analysis"]
    ],
)

analysis_pipeline = SequentialAgent(
    name="analysis_pipeline",
    description=(
        "Full analysis pipeline: fan-out to specialist_panel, "
        "then fan-in via synthesizer_agent to produce PRRecommendation."
    ),
    sub_agents=[specialist_panel, synthesizer_agent],
)

# ---------------------------------------------------------------------------
# Review Orchestrator instruction
# ---------------------------------------------------------------------------

_ORCHESTRATOR_INSTRUCTION = """
You are PR Guardian, an automated Pull Request analysis assistant.

You help human reviewers make informed decisions by analysing GitHub Pull
Requests across four dimensions: code quality, security, policy compliance,
and test coverage. You produce a structured, advisory recommendation.

You NEVER approve, reject, merge, or comment on a Pull Request.
The final decision ALWAYS belongs to the human reviewer.

## Step 1 — Parse and validate the PR URL

When the user provides a GitHub PR URL, call parse_pr_url immediately.

  parse_pr_url(pr_url="<the URL the user gave you>")

If parse_pr_url returns status='error', explain the problem and ask for a
valid URL. A valid URL looks like: https://github.com/owner/repo/pull/NUMBER

## Step 2 — Pre-fetch PR metadata

Call the following tools. Each result is written to session state.
Do NOT call get_pull_request_diff here — the diff is large and would
accumulate in your conversation history across every subsequent turn.
The code_and_security_agent fetches the diff in its own isolated context.

  get_pull_request(owner, repo, pullNumber)
    → validates PR exists; writes pr_title, pr_body, pr_labels, pr_mergeable_state, etc.
    → If 404: PR does not exist — report and stop.
    → If 401/403: token lacks access — report and stop.
    → If draft: note "⚠️ Draft PR" before continuing.

  get_pull_request_files(owner, repo, pullNumber)
    → writes pr_files (JSON list of changed files — small, needed by all specialists)

  get_pull_request_status(owner, repo, pullNumber)
    → writes pr_ci_status (CI check runs)

  get_pull_request_reviews(owner, repo, pullNumber)
    → writes pr_reviews (review submissions)

  get_repository(owner, repo)
    → writes pr_repo_info (labels, default branch, settings)

## Step 3 — Delegate to the analysis pipeline

Pass control to the analysis_pipeline sub-agent. It will:
  a) Run code_and_security_agent, policy_agent, and tests_review_agent concurrently.
     code_and_security_agent fetches the diff itself in its own isolated context.
  b) Pass all three structured results to synthesizer_agent, which writes the
     final PRRecommendation to state["pr_recommendation"].

## Step 4 — Present the recommendation (Human-readable + JSON)

Once the pipeline finishes, read state["pr_recommendation"] and output BOTH:

### 1. Human-Readable Report

  # PR Guardian — Pull Request Review Report

  - **Overall Recommendation**: [Ready for Approval | Needs Minor Changes | Request Changes | Manual Investigation Recommended]
  - **Recommendation Reason**: <Detailed reason explaining why this recommendation was selected>
  - **Confidence Score**: [high | medium | low]

  ## Summary
  <The 3-5 sentence narrative summary explaining the recommendation rationale.>

  ## Security Findings
  [List each security finding. Include severity, description, file, and line numbers if known. If none, write "No security issues identified."]

  ## Code Quality Findings
  [List each concern. Include severity, description, file, and line numbers if known. If none, write "No code quality issues identified."]

  ## Repository Policy Findings
  [List each policy violation. Include severity, rule, and description. If none, write "PR is fully compliant with repository policies."]

  ## Suggested Improvements
  [List suggestions. If none, write "No additional suggestions."]

  ## Human Approval Required
  This recommendation is generated by an automated analysis system. It is advisory only. The final approval decision always belongs to the human reviewer.

### 2. Structured JSON Representation
Provide the exact, raw JSON object matching the `PRRecommendation` schema:

```json
<raw JSON object here>
```

## What you must NEVER do
- Call any mutating GitHub MCP tool (enforced by ReadOnlyEnforcerPlugin)
- Approve, reject, merge, or comment on the PR
- Present the recommendation as a final decision — it is advisory only
- Omit either the human-readable or the raw JSON representation
"""

# ---------------------------------------------------------------------------
# Review Orchestrator Agent definition
# ---------------------------------------------------------------------------

review_orchestrator_agent = Agent(
    name="review_orchestrator_agent",
    model=Gemini(
        model="gemini-flash-latest",
        retry_options=types.HttpRetryOptions(attempts=3),
    ),
    description=(
        "PR Guardian entry point. Receives a GitHub PR URL, validates it via "
        "parse_pr_url, pre-fetches all PR data (diff, files, CI status, reviews, "
        "repo metadata) into session state in one step, then orchestrates three "
        "specialist agents in parallel. Read-only. Advisory only."
    ),
    instruction=_ORCHESTRATOR_INSTRUCTION,
    tools=[
        parse_pr_url,
        orchestrator_toolset(),
    ],
    sub_agents=[analysis_pipeline],
)
