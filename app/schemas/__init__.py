"""Pydantic schemas for PR Guardian structured outputs."""

from .analysis import (
    CodeAnalysisResult,
    CodeQualityResult,
    Concern,
    ContextAnalysisResult,
    PolicyResult,
    PolicyViolation,
    PromptInjectionRisk,
    SecurityAnalysisResult,
    SecurityFinding,
    SecurityResult,
    TestsAnalysisResult,
)
from .recommendation import Issue, PRRecommendation

__all__ = [
    # Legacy schemas (kept for backwards compatibility)
    "CodeAnalysisResult",
    # Current specialist output schemas
    "CodeQualityResult",
    # Shared primitives
    "Concern",
    "ContextAnalysisResult",
    "Issue",
    "PRRecommendation",
    "PolicyResult",
    "PolicyViolation",
    "PromptInjectionRisk",
    "SecurityAnalysisResult",
    "SecurityFinding",
    "SecurityResult",
    "TestsAnalysisResult",
]
