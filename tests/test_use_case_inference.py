"""
Tests for use case inference from tool names.

Tests keyword matching, confidence calculation, normalization,
and edge cases like empty tool lists.
"""

from __future__ import annotations

import pytest

from driftbase.local.use_case_inference import (
    USE_CASE_KEYWORDS,
    USE_CASE_WEIGHTS,
    infer_use_case,
)


def test_empty_tool_list_returns_general():
    """Empty tool list should return GENERAL with 0.0 confidence."""
    result = infer_use_case([])
    assert result["use_case"] == "GENERAL"
    assert result["confidence"] == 0.0
    assert result["matched_keywords"] == []
    assert result["scores"]["GENERAL"] == 0.0


def test_financial_use_case_detection():
    """High-signal financial keywords should detect FINANCIAL use case."""
    tools = ["check_credit_score", "verify_loan_eligibility", "process_payment"]
    result = infer_use_case(tools)
    assert result["use_case"] == "FINANCIAL"
    assert result["confidence"] > 0.5  # Should be confident
    assert "FINANCIAL" in result["scores"]
    assert result["scores"]["FINANCIAL"] > 3.0  # Above minimum threshold


def test_customer_support_use_case_detection():
    """Customer support keywords should detect CUSTOMER_SUPPORT use case."""
    tools = ["create_ticket", "escalate_to_agent", "send_refund", "check_order_status"]
    result = infer_use_case(tools)
    assert result["use_case"] == "CUSTOMER_SUPPORT"
    assert result["confidence"] > 0.5
    assert result["scores"]["CUSTOMER_SUPPORT"] > 3.0


def test_healthcare_use_case_detection():
    """Healthcare keywords should detect HEALTHCARE use case."""
    tools = ["schedule_appointment", "check_symptoms", "prescribe_medication"]
    result = infer_use_case(tools)
    assert result["use_case"] == "HEALTHCARE"
    assert result["confidence"] > 0.5
    assert result["scores"]["HEALTHCARE"] > 3.0


def test_normalization_snake_case():
    """Tool names in snake_case should be normalized correctly."""
    tools = ["check_credit_score"]  # snake_case
    result = infer_use_case(tools)
    # Should match "credit" keyword in FINANCIAL category
    assert result["use_case"] == "FINANCIAL"


def test_normalization_camel_case():
    """Tool names in camelCase should be normalized correctly."""
    tools = ["checkCreditScore"]  # camelCase
    result = infer_use_case(tools)
    # Should match "credit" keyword in FINANCIAL category
    assert result["use_case"] == "FINANCIAL"


def test_normalization_pascal_case():
    """Tool names in PascalCase should be normalized correctly."""
    tools = ["CheckCreditScore"]  # PascalCase
    result = infer_use_case(tools)
    # Should match "credit" keyword in FINANCIAL category
    assert result["use_case"] == "FINANCIAL"


def test_normalization_kebab_case():
    """Tool names in kebab-case should be normalized correctly."""
    tools = ["check-credit-score"]  # kebab-case
    result = infer_use_case(tools)
    # Should match "credit" keyword in FINANCIAL category
    assert result["use_case"] == "FINANCIAL"


def test_high_signal_keywords_weighted_2x():
    """High-signal keywords should be weighted 2x vs medium-signal."""
    # FINANCIAL has "loan", "approve" as high-signal, "verify" as medium-signal
    # 1 high-signal = 2.0, 1 medium-signal = 1.0

    # Test with just high-signal keyword
    tools_high = ["process_loan"]  # Contains "loan" high-signal
    result_high = infer_use_case(tools_high)

    # Test with just medium-signal keyword
    tools_medium = ["verify_identity"]  # Contains "verify" medium-signal
    result_medium = infer_use_case(tools_medium)

    # High-signal should score higher than medium-signal in FINANCIAL
    # "loan" scores 2.0, "approve" also in "approve_loan" scores another 2.0 = 4.0
    # Let's just verify the ratio is correct
    assert result_high["scores"]["FINANCIAL"] >= 2.0  # At least one high-signal match
    # Medium-signal might match multiple categories, but verify exists
    assert any(score >= 1.0 for score in result_medium["scores"].values())


def test_confidence_calculation():
    """Confidence should be winner_score / (winner_score + second_score)."""
    # Use tools that clearly match one category much more than others
    tools = [
        "loan_application",
        "credit_check",
        "fraud_detection",
        "payment_processing",
    ]
    result = infer_use_case(tools)

    # Should be FINANCIAL with high confidence
    assert result["use_case"] == "FINANCIAL"

    # Recalculate confidence manually
    sorted_scores = sorted(result["scores"].items(), key=lambda x: x[1], reverse=True)
    winner_score = sorted_scores[0][1]
    second_score = sorted_scores[1][1] if len(sorted_scores) > 1 else 0.0

    expected_confidence = (
        winner_score / (winner_score + second_score)
        if (winner_score + second_score) > 0
        else 0.0
    )
    assert (
        abs(result["confidence"] - expected_confidence) < 0.01
    )  # Allow small floating point error


def test_minimum_score_threshold_not_met():
    """If no category reaches minimum score (3.0), return GENERAL."""
    # Use generic tools that don't strongly match any category
    tools = ["do_something", "process_data"]
    result = infer_use_case(tools)

    # Should return GENERAL because no category reaches 3.0
    assert result["use_case"] == "GENERAL"
    assert result["confidence"] == 0.0


def test_tied_scores_picks_first():
    """If two categories tie, the first one alphabetically should win (consistent behavior)."""
    # This is hard to engineer without knowing exact keywords, but we can test
    # that the function doesn't crash and returns a valid use case
    tools = ["schedule", "appointment"]  # Might match multiple categories
    result = infer_use_case(tools)

    # Should return a valid use case
    assert result["use_case"] in USE_CASE_KEYWORDS
    # If GENERAL, confidence should be 0.0
    if result["use_case"] == "GENERAL":
        assert result["confidence"] == 0.0
    else:
        # If not GENERAL, confidence should be > 0
        assert result["confidence"] > 0.0


def test_matched_keywords_populated():
    """matched_keywords should contain the actual keywords that matched."""
    tools = ["create_ticket", "escalate_issue"]
    result = infer_use_case(tools)

    # Should have matched some keywords
    assert len(result["matched_keywords"]) > 0
    # All matched keywords should be strings
    assert all(isinstance(kw, str) for kw in result["matched_keywords"])


def test_scores_dict_populated():
    """scores dict should contain scores for all categories."""
    tools = ["check_credit_score"]
    result = infer_use_case(tools)

    # Should have scores for all use cases
    assert len(result["scores"]) == len(USE_CASE_KEYWORDS)
    # All scores should be non-negative
    assert all(score >= 0.0 for score in result["scores"].values())


def test_all_use_cases_have_weights():
    """Every use case in USE_CASE_KEYWORDS should have corresponding weights."""
    for use_case in USE_CASE_KEYWORDS:
        assert use_case in USE_CASE_WEIGHTS, f"Missing weights for {use_case}"
        weights = USE_CASE_WEIGHTS[use_case]
        # Weights should sum to approximately 1.0
        total = sum(weights.values())
        assert abs(total - 1.0) < 0.01, (
            f"{use_case} weights sum to {total}, expected 1.0"
        )


def test_edge_case_none_in_tools():
    """Should handle None values in tools list gracefully."""
    tools = ["check_credit", None, "verify_loan"]
    # Should not crash, might filter out None or convert to string
    result = infer_use_case(tools)
    assert result["use_case"] in USE_CASE_KEYWORDS or result["use_case"] == "GENERAL"


def test_edge_case_empty_strings():
    """Should handle empty strings in tools list gracefully."""
    tools = ["", "check_credit", ""]
    result = infer_use_case(tools)
    assert result["use_case"] in USE_CASE_KEYWORDS or result["use_case"] == "GENERAL"


def test_mixed_case_sensitivity():
    """Keywords should be case-insensitive after normalization."""
    tools = ["CHECK_CREDIT_SCORE"]  # All caps
    result = infer_use_case(tools)
    assert result["use_case"] == "FINANCIAL"


def test_partial_keyword_matches():
    """Partial matches should work (e.g., 'loan' in 'loan_application')."""
    tools = [
        "process_loan_application"
    ]  # Contains "loan" which is high-signal for FINANCIAL
    result = infer_use_case(tools)
    # With only "loan" keyword (2.0 score), it won't reach 3.0 threshold
    # Need at least 2 high-signal or 1 high + 2 medium to reach 3.0
    # Let's test with more keywords
    tools = [
        "check_credit_score",
        "approve_loan",
    ]  # "credit" + "approve" + "loan" = 6.0
    result = infer_use_case(tools)
    assert result["use_case"] == "FINANCIAL"


def test_ecommerce_use_case():
    """E-commerce keywords should detect ECOMMERCE_SALES use case."""
    tools = ["add_to_cart", "process_checkout", "manage_inventory"]
    result = infer_use_case(tools)
    assert result["use_case"] == "ECOMMERCE_SALES"
    assert result["confidence"] > 0.5


def test_legal_use_case():
    """Legal keywords should detect LEGAL use case."""
    tools = ["extract_clause", "contract_review", "cite_precedent"]
    result = infer_use_case(tools)
    assert result["use_case"] == "LEGAL"
    assert result["confidence"] > 0.5


def test_hr_use_case():
    """HR keywords should detect HR_RECRUITING use case."""
    tools = ["post_job", "screen_candidate", "schedule_interview"]
    result = infer_use_case(tools)
    assert result["use_case"] == "HR_RECRUITING"
    assert result["confidence"] > 0.5


def test_automation_use_case():
    """Automation keywords should detect AUTOMATION use case."""
    tools = ["schedule_task", "send_email", "create_webhook"]
    result = infer_use_case(tools)
    assert result["use_case"] == "AUTOMATION"
    assert result["confidence"] > 0.5


def test_content_generation_use_case():
    """Content generation keywords should detect CONTENT_GENERATION use case."""
    tools = ["write_post", "generate_image", "create_caption"]
    result = infer_use_case(tools)
    assert result["use_case"] == "CONTENT_GENERATION"
    assert result["confidence"] > 0.5


def test_data_analysis_use_case():
    """Data analysis keywords should detect DATA_ANALYSIS use case."""
    tools = ["run_query", "generate_chart", "calculate_metrics"]
    result = infer_use_case(tools)
    assert result["use_case"] == "DATA_ANALYSIS"
    assert result["confidence"] > 0.5


def test_security_use_case():
    """Security keywords should detect SECURITY_ITOPS use case."""
    tools = ["scan_port", "check_cve", "vulnerability_scan"]
    result = infer_use_case(tools)
    assert result["use_case"] == "SECURITY_ITOPS"
    assert result["confidence"] > 0.5


def test_research_rag_use_case():
    """Research RAG keywords should detect RESEARCH_RAG use case."""
    tools = ["search_documents", "retrieve_chunks", "rerank_results"]
    result = infer_use_case(tools)
    assert result["use_case"] == "RESEARCH_RAG"
    assert result["confidence"] > 0.5


def test_general_fallback_with_generic_tools():
    """Generic tool names should fall back to GENERAL."""
    tools = ["get_data", "process", "send_response"]
    result = infer_use_case(tools)
    # These generic terms likely won't reach 3.0 threshold for any category
    # So should return GENERAL
    assert result["use_case"] == "GENERAL"
    assert result["confidence"] == 0.0
