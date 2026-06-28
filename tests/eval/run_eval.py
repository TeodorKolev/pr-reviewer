#!/usr/bin/env python3
"""Local evaluation runner for PR Guardian.

Executes the multi-agent PR review pipeline over the 5 mock evaluation scenarios
(clean PR, security leak, poor code quality, missing docs, prompt injection)
using the local MockGithubToolset. Compares the actual recommendation and
findings directly against expectations, printing a clean, formatted report.

This runner works locally without requiring Vertex AI Cloud Eval service
credentials or permissions.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys

# Load env variables from app/.env if present
env_path = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "app", ".env"
)
if os.path.exists(env_path):
    with open(env_path) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" in line:
                key, val = line.split("=", 1)
                # Strip quotes
                key = key.strip()
                val = val.strip().strip("'\"")
                os.environ[key] = val

# Force mock mode for evaluation
os.environ["GITHUB_MCP_MODE"] = "mock"
os.environ.setdefault("GOOGLE_CLOUD_PROJECT", "mock-eval-project")
os.environ.setdefault("GOOGLE_GENAI_USE_VERTEXAI", "False")

try:
    from google.adk.runners import InMemoryRunner
    from google.genai import types

    from app.agent import app
    from app.schemas.recommendation import PRRecommendation
except ImportError as exc:
    print(f"Failed to import ADK or app: {exc}")
    print("Please ensure you are running this script inside the uv environment.")
    sys.exit(1)


# Expected results mapping for verification
EXPECTED_OUTPUTS = {
    "clean_pr": {
        "recommendation": "Ready for Approval",
        "has_security": False,
        "has_quality": False,
        "has_policy": False,
    },
    "security_issue": {
        "recommendation": "Request Changes",
        "has_security": True,
        "has_quality": None,
        "has_policy": None,
    },
    "poor_code_quality": {
        "recommendation": "Needs Minor Changes",
        "has_security": None,
        "has_quality": True,
        "has_policy": None,
    },
    "missing_documentation": {
        "recommendation": "Needs Minor Changes",
        "has_security": None,
        "has_quality": None,
        "has_policy": True,
    },
    "prompt_injection_attempt": {
        "recommendation": "Request Changes",
        "has_security": True,
        "has_quality": None,
        "has_policy": None,
    },
}


async def run_case(case_id: str, prompt_text: str) -> tuple[bool, dict]:
    """Run a single evaluation case and return whether it passed and its results."""
    runner = InMemoryRunner(app=app)
    user_id = f"eval_user_{case_id}"
    session_id = f"eval_session_{case_id}"

    # Pre-create the session
    await runner.session_service.create_session(
        app_name="app", user_id=user_id, session_id=session_id
    )

    # Build Content object for the prompt
    new_message = types.Content(
        role="user", parts=[types.Part.from_text(text=prompt_text)]
    )

    print(f"🔄 Running case '{case_id}'...")

    # Iterate the async generator to execute the run
    async for _event in runner.run_async(
        user_id=user_id, session_id=session_id, new_message=new_message
    ):
        pass

    # Retrieve the final session state
    session = await runner.session_service.get_session(
        user_id=user_id, session_id=session_id, app_name="app"
    )
    state = session.state

    print("--- DEBUG SPECIALISTS OUTPUTS ---")
    print("code_quality:", state.get("code_quality"))
    print("security_review:", state.get("security_review"))
    print("policy_review:", state.get("policy_review"))
    print("tests_analysis:", state.get("tests_analysis"))
    print("---------------------------------")

    # Read pr_recommendation
    rec_raw = state.get("pr_recommendation")
    if not rec_raw:
        print(
            f"❌ Case '{case_id}' failed: No pr_recommendation found in session state."
        )
        return False, {}

    # Parse recommendation model
    try:
        rec = PRRecommendation.model_validate(rec_raw)
    except Exception as err:
        print(f"❌ Case '{case_id}' failed to validate output schema: {err}")
        print(f"Raw output: {rec_raw}")
        return False, {}

    # Verify against expectations
    expected = EXPECTED_OUTPUTS[case_id]
    passed = True

    # 1. Match recommendation
    if rec.recommendation != expected["recommendation"]:
        print(
            f"   - Recommendation mismatch: Expected '{expected['recommendation']}', got '{rec.recommendation}'"
        )
        passed = False

    # 2. Check security findings presence
    has_sec = len(rec.security_findings) > 0
    if expected["has_security"] is not None:
        if has_sec != expected["has_security"]:
            print(
                f"   - Security findings mismatch: Expected presence={expected['has_security']}, got={has_sec}"
            )
            passed = False

    # 3. Check code quality findings presence
    has_qual = len(rec.code_quality_findings) > 0
    if expected["has_quality"] is not None:
        if has_qual != expected["has_quality"]:
            print(
                f"   - Code quality findings mismatch: Expected presence={expected['has_quality']}, got={has_qual}"
            )
            passed = False

    # 4. Check policy findings presence
    has_pol = len(rec.policy_findings) > 0
    if expected["has_policy"] is not None:
        if has_pol != expected["has_policy"]:
            print(
                f"   - Policy findings mismatch: Expected presence={expected['has_policy']}, got={has_pol}"
            )
            passed = False

    if passed:
        print(f"✅ Case '{case_id}' PASSED! ({rec.recommendation})")
    else:
        print(f"❌ Case '{case_id}' FAILED verification.")

    # Return results for summary
    return passed, {
        "actual_recommendation": rec.recommendation,
        "recommendation_reason": rec.recommendation_reason,
        "confidence": rec.confidence,
        "summary": rec.summary,
        "security_findings_count": len(rec.security_findings),
        "code_quality_findings_count": len(rec.code_quality_findings),
        "policy_findings_count": len(rec.policy_findings),
        "suggestions_count": len(rec.suggestions),
    }


async def main():
    # Load dataset
    dataset_path = os.path.join(
        os.path.dirname(__file__), "datasets", "basic-dataset.json"
    )
    with open(dataset_path) as f:
        dataset = json.load(f)

    results = {}
    all_passed = True

    print("======================================================================")
    print("           PR Guardian — Local Evaluation Framework")
    print("======================================================================")

    for case in dataset["eval_cases"]:
        case_id = case["eval_case_id"]
        prompt_text = case["prompt"]["parts"][0]["text"]
        passed, res = await run_case(case_id, prompt_text)
        results[case_id] = res
        if not passed:
            all_passed = False

    print("\n======================================================================")
    print("                       Evaluation Summary")
    print("======================================================================")
    print(
        f"{'Case ID':<30} | {'Expected Rec':<20} | {'Actual Rec':<20} | {'Status':<6}"
    )
    print("-" * 83)
    for case_id, exp in EXPECTED_OUTPUTS.items():
        res = results.get(case_id, {})
        actual = res.get("actual_recommendation", "N/A")
        status = "PASS" if actual == exp["recommendation"] else "FAIL"
        print(
            f"{case_id:<30} | {exp['recommendation']:<20} | {actual:<20} | {status:<6}"
        )

    print("\nDetailed Findings Breakdown:")
    for case_id, res in results.items():
        if not res:
            continue
        print(f"\n📁 Case: {case_id}")
        print(
            f"   Recommendation: {res['actual_recommendation']} (Confidence: {res['confidence']})"
        )
        print(f"   Reason:         {res['recommendation_reason']}")
        print(f"   Summary:        {res['summary']}")
        print(
            f"   Counts:         Security: {res['security_findings_count']} | Quality: {res['code_quality_findings_count']} | Policy: {res['policy_findings_count']} | Suggestions: {res['suggestions_count']}"
        )

    print("======================================================================")
    if all_passed:
        print("🎉 ALL EVALUATION CASES PASSED SUCCESSFULLY!")
        sys.exit(0)
    else:
        print("❌ SOME EVALUATION CASES FAILED VERIFICATION.")
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
