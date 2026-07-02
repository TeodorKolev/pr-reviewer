"""Pydantic schemas for each specialist agent's analysis output.

Schema inventory:
  Shared primitives:
    - Concern              — a code-level issue with file/line location
    - SecurityFinding      — a security finding with severity and category
    - PromptInjectionRisk  — AI/LLM-specific injection risk (new)
    - PolicyViolation      — a repository policy rule that was violated (new)

  Specialist output schemas (one per agent, consumed by the synthesizer):
    - CodeQualityResult    — code_quality_agent output
    - SecurityResult       — security_agent output
    - PolicyResult         — policy_agent output
    - TestsAnalysisResult  — tests_review_agent output (unchanged)

  Legacy schemas kept for backwards compatibility during transition:
    - CodeAnalysisResult   — superseded by CodeQualityResult
    - SecurityAnalysisResult — superseded by SecurityResult
    - ContextAnalysisResult  — superseded by PolicyResult
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

# ---------------------------------------------------------------------------
# Shared primitives
# ---------------------------------------------------------------------------


class Concern(BaseModel):
    """A specific concern identified in the code."""

    description: str = Field(description="Clear description of the concern.")
    file: str | None = Field(default=None, description="Affected file path, if known.")
    line_range: list[int] | None = Field(
        default=None,
        description="Start and end line numbers [start, end], if applicable.",
    )
    severity: Literal["high", "medium", "low", "info"] = Field(
        default="medium", description="Severity level of the concern."
    )


class SecurityFinding(BaseModel):
    """A security finding identified in the diff."""

    severity: Literal["critical", "high", "medium", "low", "info"] = Field(
        description="Severity level of the security finding."
    )
    description: str = Field(description="Clear description of the security issue.")
    file: str | None = Field(default=None, description="Affected file path, if known.")
    line_range: list[int] | None = Field(
        default=None,
        description="Start and end line numbers [start, end], if applicable.",
    )
    category: str = Field(
        default="general",
        description=(
            "Category: 'hardcoded-secret', 'injection', 'unsafe-dependency', "
            "'missing-validation', 'dangerous-import', 'dangerous-pattern'."
        ),
    )


class PromptInjectionRisk(BaseModel):
    """An AI/LLM-specific prompt injection or data poisoning risk."""

    description: str = Field(
        description=(
            "Clear description of the prompt injection risk and why it is dangerous."
        )
    )
    file: str | None = Field(default=None, description="Affected file path, if known.")
    line_range: list[int] | None = Field(
        default=None,
        description="Start and end line numbers [start, end], if applicable.",
    )
    risk_pattern: str = Field(
        description=(
            "Pattern type: 'user_input_in_prompt', 'unsanitised_format_string', "
            "'jinja_template_injection', 'dynamic_system_prompt', "
            "'untrusted_tool_output_in_context', 'indirect_injection_via_file'."
        )
    )
    severity: Literal["critical", "high", "medium", "low"] = Field(
        description="Severity level of the prompt injection risk."
    )


class PolicyViolation(BaseModel):
    """A repository policy rule that the PR is violating."""

    rule: str = Field(
        description=(
            "Short machine-readable rule name, e.g. 'missing_required_label', "
            "'no_linked_issue', 'changelog_not_updated', 'missing_docs_update', "
            "'codeowners_not_satisfied'."
        )
    )
    description: str = Field(
        description="Human-readable explanation of the violation and how to fix it."
    )
    severity: Literal["blocking", "warning", "info"] = Field(
        description=(
            "'blocking' = PR should not be merged until resolved; "
            "'warning' = should be addressed but not a hard blocker; "
            "'info' = informational, reviewer's discretion."
        )
    )


# ---------------------------------------------------------------------------
# Specialist output schemas (new — aligned with user-defined agents)
# ---------------------------------------------------------------------------


class CodeQualityResult(BaseModel):
    """Structured output from the code_quality_agent.

    Covers complexity, maintainability, code duplication, naming consistency,
    and adherence to project conventions.
    """

    overall_score: int = Field(
        ge=0,
        le=100,
        description=(
            "Overall code quality score (0 = very poor, 100 = excellent). "
            "Weighted average of complexity, maintainability, and conventions."
        ),
    )
    complexity_score: int = Field(
        ge=0,
        le=100,
        description=(
            "Score for cyclomatic and cognitive complexity: "
            "100 = simple and well-decomposed, 0 = deeply nested / high branching."
        ),
    )
    maintainability_score: int = Field(
        ge=0,
        le=100,
        description=(
            "Score for long-term maintainability: readability, single-responsibility, "
            "clear abstractions, appropriate comments."
        ),
    )
    duplicated_logic: list[Concern] = Field(
        default_factory=list,
        description=(
            "Instances of copy-pasted or near-duplicate logic that should be extracted "
            "into a shared function or module."
        ),
    )
    naming_issues: list[Concern] = Field(
        default_factory=list,
        description=(
            "Inconsistent, misleading, or non-conventional identifier names "
            "(variables, functions, classes, modules)."
        ),
    )
    convention_violations: list[Concern] = Field(
        default_factory=list,
        description=(
            "Violations of the project's established coding conventions: "
            "style, structure, patterns, or idioms observed in the surrounding codebase."
        ),
    )
    positive_patterns: list[str] = Field(
        default_factory=list,
        description="Notable good practices or patterns observed in the changed code.",
    )
    summary: str = Field(
        description=(
            "2-3 sentence narrative summarising the code quality findings "
            "and the most important improvement opportunities."
        )
    )


class SecurityResult(BaseModel):
    """Structured output from the security_agent.

    Covers secrets exposure, dangerous code patterns, dependency risks,
    and AI/LLM-specific prompt injection vulnerabilities.
    """

    has_critical_issues: bool = Field(
        description=(
            "True if any finding (across all categories) has severity='critical'. "
            "A critical issue should block approval."
        )
    )
    overall_risk_level: Literal["critical", "high", "medium", "low", "none"] = Field(
        description=(
            "Highest risk level across all findings. 'none' means no findings."
        )
    )
    secrets_findings: list[SecurityFinding] = Field(
        default_factory=list,
        description=(
            "Hardcoded secrets, credentials, API keys, tokens, or private keys "
            "found in the changed code or configuration."
        ),
    )
    dangerous_pattern_findings: list[SecurityFinding] = Field(
        default_factory=list,
        description=(
            "Dangerous code patterns: injection risks (SQL, command, LDAP), "
            "eval/exec, path traversal, missing input validation, "
            "authentication gaps, sensitive data exposure."
        ),
    )
    dependency_findings: list[SecurityFinding] = Field(
        default_factory=list,
        description=(
            "Newly added or updated dependencies with known vulnerabilities, "
            "suspicious provenance, or questionable licensing."
        ),
    )
    prompt_injection_findings: list[PromptInjectionRisk] = Field(
        default_factory=list,
        description=(
            "AI/LLM-specific risks: untrusted user input injected into prompts, "
            "unsanitised format strings in LLM calls, dynamic system prompt construction, "
            "indirect injection via external tool outputs or files."
        ),
    )
    summary: str = Field(
        description=(
            "2-3 sentence narrative summarising the security findings. "
            "If no issues were found, state that clearly."
        )
    )


class PolicyResult(BaseModel):
    """Structured output from the policy_agent.

    Checks repository governance rules: required labels, linked issues,
    changelog updates, documentation requirements, and other repo-specific policies.
    """

    compliant: bool = Field(
        description=(
            "True if there are no 'blocking' policy violations. "
            "A non-compliant PR should not be merged until violations are resolved."
        )
    )
    has_required_labels: bool = Field(
        description=(
            "True if all labels required by the repository's policy are present on the PR."
        )
    )
    present_labels: list[str] = Field(
        default_factory=list,
        description="Labels currently applied to the PR.",
    )
    missing_labels: list[str] = Field(
        default_factory=list,
        description=(
            "Labels that appear to be required but are not present on the PR. "
            "e.g. 'type/bugfix', 'needs-changelog', 'breaking-change'."
        ),
    )
    linked_issue_status: Literal["present", "missing", "not_required"] = Field(
        description=(
            "'present' = PR body links a GitHub issue (Fixes #N, Closes #N, etc.); "
            "'missing' = no linked issue found but one appears required; "
            "'not_required' = repository does not mandate linked issues."
        )
    )
    changelog_updated: bool | None = Field(
        default=None,
        description=(
            "True if a CHANGELOG or CHANGES file was modified in this PR. "
            "False if it was not. None if the repository has no changelog convention."
        ),
    )
    documentation_updated: bool | None = Field(
        default=None,
        description=(
            "True if documentation files (docs/, README, *.md) were updated "
            "alongside source code changes. False if docs appear stale. "
            "None if the PR is purely a docs change or no docs are required."
        ),
    )
    violations: list[PolicyViolation] = Field(
        default_factory=list,
        description="All policy violations found, ordered by severity (blocking first).",
    )
    summary: str = Field(
        description=(
            "2-3 sentence narrative summarising the policy compliance status "
            "and any required actions before the PR can be merged."
        )
    )


# ---------------------------------------------------------------------------
# Legacy schemas — kept for backwards compatibility, superseded by the above
# ---------------------------------------------------------------------------


class CodeAnalysisResult(BaseModel):
    """Legacy: superseded by CodeQualityResult."""

    score: int = Field(ge=0, le=100, description="Overall code quality score.")
    concerns: list[Concern] = Field(default_factory=list)
    positives: list[str] = Field(default_factory=list)
    summary: str = Field(description="Code quality narrative.")


class SecurityAnalysisResult(BaseModel):
    """Legacy: superseded by SecurityResult."""

    has_critical_issues: bool
    findings: list[SecurityFinding] = Field(default_factory=list)
    dependency_changes_reviewed: bool = Field(default=False)
    summary: str


class TestsAnalysisResult(BaseModel):
    """Structured output from the tests_review_agent (unchanged)."""

    ci_passing: bool | None = Field(
        default=None,
        description=(
            "True if all CI checks are passing, False if any failed, "
            "None if CI is pending or not configured."
        ),
    )
    coverage_adequate: bool = Field(
        description=(
            "True if the changed code has meaningful test coverage. "
            "False if new/changed logic lacks corresponding tests."
        )
    )
    test_quality_score: int = Field(
        ge=0,
        le=100,
        description=(
            "Quality score for the tests themselves: do they cover edge cases, "
            "use meaningful assertions, avoid excessive mocking?"
        ),
    )
    missing_coverage: list[str] = Field(
        default_factory=list,
        description="Files or modules that appear to lack test coverage.",
    )
    summary: str = Field(
        description="2-3 sentence narrative summarising the test and CI findings."
    )


class ContextAnalysisResult(BaseModel):
    """Legacy: superseded by PolicyResult."""

    description_quality: Literal["good", "adequate", "poor", "missing"] = Field(
        default="adequate"
    )
    has_linked_issues: bool = Field(default=False)
    pr_size: Literal["xs", "s", "m", "l", "xl"] = Field(default="m")
    scope_concerns: list[str] = Field(default_factory=list)
    summary: str = Field(default="")


class CodeAndSecurityResult(BaseModel):
    """Combined output from code_and_security_agent.

    Merges CodeQualityResult and SecurityResult into a single schema so both
    analyses can be produced in one LLM call, halving diff-injection overhead.
    """

    code_quality: CodeQualityResult = Field(
        description="Code quality analysis: complexity, maintainability, duplication, naming."
    )
    security: SecurityResult = Field(
        description="Security analysis: secrets, dangerous patterns, dependencies, prompt injection."
    )
