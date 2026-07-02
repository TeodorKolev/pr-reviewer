"""Agents package for PR Guardian.

Agent inventory:
  Orchestration:
    review_orchestrator_agent  — root entry point; coordinates all others
    analysis_pipeline          — SequentialAgent: panel → synthesizer
    specialist_panel           — ParallelAgent: three specialists concurrent

  Specialist agents (run in parallel):
    code_and_security_agent    — code quality + security (single-turn, no tools)
    policy_agent               — labels, linked issues, changelog, docs, repo rules
    tests_review_agent         — CI status and test coverage (single-turn, no tools)

  Aggregation:
    synthesizer_agent          — merges all specialist outputs into PRRecommendation
"""

from .code_and_security_agent import code_and_security_agent
from .policy_agent import policy_agent
from .review_orchestrator_agent import (
    analysis_pipeline,
    review_orchestrator_agent,
    specialist_panel,
)
from .synthesizer_agent import synthesizer_agent
from .tests_review_agent import tests_review_agent

__all__ = [
    "analysis_pipeline",
    # Specialists
    "code_and_security_agent",
    "policy_agent",
    # Orchestration
    "review_orchestrator_agent",
    "specialist_panel",
    # Aggregation
    "synthesizer_agent",
    "tests_review_agent",
]
