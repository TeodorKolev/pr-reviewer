"""Review Orchestrator Agent — entry point and coordinator for PR Guardian.

Receives a GitHub Pull Request URL, validates it, stores owner/repo/pull_number
in session state, then orchestrates all specialist agents via the analysis pipeline.

Session state written by this agent (via parse_pr_url tool):
  pr_owner        — repository owner, e.g. "google"
  pr_repo         — repository name, e.g. "adk-python"
  pr_pull_number  — PR number as int, e.g. 42
  pr_url          — canonical PR URL

These state keys are read by all specialist agents via instruction interpolation:
  {pr_owner}, {pr_repo}, {pr_pull_number}, {pr_url}

Agent topology:
  review_orchestrator_agent
    │── parse_pr_url       (local Python tool — sets session state)
    │── get_pull_request   (GitHub MCP — validates PR exists, loads header)
    └── analysis_pipeline  (SequentialAgent)
          ├── specialist_panel (ParallelAgent)
          │     ├── code_quality_agent   → state["code_quality"]
          │     ├── security_agent       → state["security_review"]
          │     ├── policy_agent         → state["policy_review"]
          │     └── tests_review_agent   → state["tests_analysis"]
          └── synthesizer_agent          → state["pr_recommendation"]
"""

from google.adk.agents import Agent, ParallelAgent, SequentialAgent
from google.adk.models import Gemini
from google.genai import types

from app.agents.code_quality_agent import code_quality_agent
from app.agents.policy_agent import policy_agent
from app.agents.security_agent import security_agent
from app.agents.synthesizer_agent import synthesizer_agent
from app.agents.tests_review_agent import tests_review_agent
from app.tools import orchestrator_toolset, parse_pr_url

# ---------------------------------------------------------------------------
# Pipeline: parallel fan-out → synthesizer fan-in
# ---------------------------------------------------------------------------

specialist_panel = ParallelAgent(
    name="specialist_panel",
    description=(
        "Runs all four PR analysis specialists concurrently via GitHub MCP. "
        "Each writes a structured JSON result to its own session state key."
    ),
    sub_agents=[
        code_quality_agent,  # → state["code_quality"]   (CodeQualityResult)
        security_agent,  # → state["security_review"] (SecurityResult)
        policy_agent,  # → state["policy_review"]   (PolicyResult)
        tests_review_agent,  # → state["tests_analysis"]  (TestsAnalysisResult)
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

This validates the URL format and writes owner, repo, and pull_number to
session state so all downstream agents can access them.

If parse_pr_url returns status='error', explain the problem and ask for a
valid URL. A valid URL looks like: https://github.com/owner/repo/pull/NUMBER

## Step 2 — Fetch the PR header

Call get_pull_request to confirm the PR exists and load its metadata:

  get_pull_request(owner=<owner>, repo=<repo>, pullNumber=<pull_number>)

  - If the call fails with 404: the PR does not exist — report this and stop.
  - If the call fails with 401/403: the GITHUB_TOKEN lacks access — report this and stop.
  - If the PR is a draft: note "⚠️ Draft PR" prominently before continuing.
  - Record the PR title, author, head branch, and base branch for use in Step 4.

## Step 3 — Delegate to the analysis pipeline

Pass control to the analysis_pipeline sub-agent. It will:
  a) Run code_quality_agent, security_agent, policy_agent, and tests_review_agent
     concurrently via the specialist_panel.
  b) Pass all four structured results to synthesizer_agent, which writes the
     final PRRecommendation to state["pr_recommendation"].

## Step 4 — Present the recommendation (Human-readable + JSON)

Once the pipeline finishes, read state["pr_recommendation"] and output BOTH of the following:

### 1. Human-Readable Report
Format the report EXACTLY with these sections:

  # PR Guardian — Pull Request Review Report

  - **Overall Recommendation**: [Ready for Approval | Needs Minor Changes | Request Changes | Manual Investigation Recommended]
  - **Recommendation Reason**: <Detailed reason explaining why this recommendation was selected>
  - **Confidence Score**: [high | medium | low]

  ## Summary
  <The 3-5 sentence narrative summary explaining the recommendation rationale.>

  ## Security Findings
  [List each security finding from security_findings. Include severity, description, file, and line numbers if known. If none, write "No security issues identified."]

  ## Code Quality Findings
  [List each concern from code_quality_findings. Include severity, description, file, and line numbers if known. If none, write "No code quality issues identified."]

  ## Repository Policy Findings
  [List each policy violation from policy_findings. Include severity, rule, and description. If none, write "PR is fully compliant with repository policies."]

  ## Suggested Improvements
  [List suggestions from suggestions list. If none, write "No additional suggestions."]

  ## Human Approval Required
  [Present the standard advisory disclaimer: "This recommendation is generated by an automated analysis system. It is advisory only. The final approval decision always belongs to the human reviewer."]

### 2. Structured JSON Representation
Provide the exact, raw JSON object matching the `PRRecommendation` schema inside a markdown code block:

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
        "parse_pr_url (session state), loads the PR header via GitHub MCP, "
        "orchestrates four specialist agents in parallel, and returns both "
        "the human-readable report and the structured JSON representation. "
        "Read-only. Advisory only."
    ),
    instruction=_ORCHESTRATOR_INSTRUCTION,
    tools=[
        parse_pr_url,  # local Python tool — parses URL + sets session state
        orchestrator_toolset(),  # GitHub MCP: get_pull_request
    ],
    sub_agents=[analysis_pipeline],
)
