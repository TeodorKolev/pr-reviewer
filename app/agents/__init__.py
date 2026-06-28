"""Agents package for PR Guardian.

Agent inventory:
  Orchestration:
    review_orchestrator_agent  — root entry point; coordinates all others
    analysis_pipeline          — SequentialAgent: panel → synthesizer
    specialist_panel           — ParallelAgent: all four specialists concurrent

  Specialist agents (run in parallel):
    code_quality_agent         — complexity, maintainability, duplication, naming, conventions
    security_agent             — secrets, dangerous patterns, dependencies, prompt injection
    policy_agent               — labels, linked issues, changelog, docs, repo rules
    tests_review_agent         — CI status and test coverage

  Aggregation:
    synthesizer_agent          — merges all specialist outputs into PRRecommendation
"""

from .code_quality_agent import code_quality_agent
from .policy_agent import policy_agent
from .review_orchestrator_agent import (
    analysis_pipeline,
    review_orchestrator_agent,
    specialist_panel,
)
from .security_agent import security_agent
from .synthesizer_agent import synthesizer_agent
from .tests_review_agent import tests_review_agent

__all__ = [
    "analysis_pipeline",
    # Specialists
    "code_quality_agent",
    "policy_agent",
    # Orchestration
    "review_orchestrator_agent",
    "security_agent",
    "specialist_panel",
    # Aggregation
    "synthesizer_agent",
    "tests_review_agent",
]
