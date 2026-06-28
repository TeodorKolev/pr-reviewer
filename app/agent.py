# ruff: noqa
# Copyright 2026 Google LLC
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     https://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""
PR Guardian — Application entry point.

This module is the ADK runtime entry point (app/__init__.py imports `app` from here).
Agent logic lives in app/agents/; this file wires the root agent into the App.

Agent topology
──────────────
review_orchestrator_agent          ← root (this file sets as root_agent)
  │
  ├── fetch_pr_metadata (tool)
  │
  └── analysis_pipeline (SequentialAgent)
        │
        ├── specialist_panel (ParallelAgent)
        │     ├── code_quality_agent   → state["code_quality"]   (CodeQualityResult)
        │     ├── security_agent       → state["security_review"] (SecurityResult)
        │     ├── policy_agent         → state["policy_review"]   (PolicyResult)
        │     └── tests_review_agent   → state["tests_analysis"]  (TestsAnalysisResult)
        │
        └── synthesizer_agent          → state["pr_recommendation"] (PRRecommendation)
"""

import os

import google.auth
from google.adk.apps import App

from app.agents.review_orchestrator_agent import review_orchestrator_agent
from app.plugins import ReadOnlyEnforcerPlugin

# ---------------------------------------------------------------------------
# GCP environment — configure Vertex AI backend
# ---------------------------------------------------------------------------

try:
    _, project_id = google.auth.default()
    if project_id:
        os.environ.setdefault("GOOGLE_CLOUD_PROJECT", project_id)
except Exception:
    pass  # Local dev with GOOGLE_API_KEY — ADC not required

os.environ.setdefault("GOOGLE_CLOUD_LOCATION", "global")
os.environ.setdefault("GOOGLE_GENAI_USE_VERTEXAI", "True")

# ---------------------------------------------------------------------------
# ADK App — root agent + safety plugin
# ---------------------------------------------------------------------------

# The root_agent alias is required by the ADK runner and eval tooling.
root_agent = review_orchestrator_agent

app = App(
    root_agent=root_agent,
    name="app",
    plugins=[ReadOnlyEnforcerPlugin()],
)
