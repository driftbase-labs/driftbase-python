"""
Use case inference from tool names.

Infers agent use case from observed tool names using keyword scoring.
Returns inferred category with confidence score for dimension weight calibration.
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

# Keyword scoring tables: high-signal keywords × 2, medium-signal × 1
USE_CASE_KEYWORDS = {
    "FINANCIAL": {
        "high": [
            "loan",
            "credit",
            "fraud",
            "payment",
            "transaction",
            "invoice",
            "billing",
            "approve",
            "reject",
            "underwrite",
            "kyc",
            "aml",
            "compliance",
            "risk score",
            "portfolio",
            "trade",
            "settlement",
            "account balance",
            "transfer",
            "refund",
            "sanction",
            "watchlist",
            "beneficiary",
            "swift",
            "iban",
            "ledger",
            "reconcile",
            "collateral",
            "margin",
            "interest rate",
        ],
        "medium": ["verify", "validate", "check", "review", "flag", "score", "audit"],
    },
    "CUSTOMER_SUPPORT": {
        "high": [
            "ticket",
            "escalate",
            "handoff",
            "resolve",
            "sentiment",
            "satisfaction",
            "complaint",
            "refund request",
            "sla",
            "priority",
            "queue",
            "agent transfer",
            "csat",
            "nps",
            "churn",
            "retention",
            "case",
            "issue",
            "support tier",
            "deflect",
            "knowledge base search",
            "macro",
            "tag ticket",
            "merge ticket",
            "reopen",
        ],
        "medium": [
            "lookup",
            "search",
            "email",
            "notify",
            "update status",
            "close",
            "assign",
        ],
    },
    "RESEARCH_RAG": {
        "high": [
            "search",
            "retrieve",
            "embed",
            "chunk",
            "index",
            "similarity",
            "rerank",
            "summarize",
            "extract",
            "cite",
            "document",
            "knowledge base",
            "vector",
            "web search",
            "arxiv",
            "pubmed",
            "scrape",
            "crawl",
            "semantic search",
            "hybrid search",
            "mmr",
            "cross encoder",
            "bm25",
            "passage retrieval",
            "fact check",
            "source verify",
            "citation lookup",
        ],
        "medium": ["query", "fetch", "load", "parse", "read", "filter", "rank"],
    },
    "CODE_GENERATION": {
        "high": [
            "execute code",
            "run tests",
            "lint",
            "compile",
            "debug",
            "git commit",
            "git push",
            "pull request",
            "code review",
            "static analysis",
            "coverage",
            "deploy",
            "dockerfile",
            "ci pipeline",
            "sandbox",
            "interpreter",
            "repl",
            "write code",
            "refactor",
            "generate function",
            "run script",
            "install package",
            "create file",
            "read file",
            "edit file",
            "diff code",
        ],
        "medium": ["bash", "terminal", "shell", "write file", "search code", "grep"],
    },
    "AUTOMATION": {
        "high": [
            "schedule",
            "cron",
            "webhook",
            "trigger",
            "workflow",
            "pipeline",
            "send email",
            "send slack",
            "notify team",
            "create task",
            "assign",
            "calendar",
            "meeting",
            "reminder",
            "integration",
            "zapier",
            "make scenario",
            "n8n",
            "rpa",
            "browser action",
            "click",
            "fill form",
            "screenshot",
            "extract data",
            "watch folder",
            "poll api",
        ],
        "medium": ["update", "create", "delete", "list", "get", "sync", "map"],
    },
    "CONTENT_GENERATION": {
        "high": [
            "write post",
            "generate image",
            "caption",
            "draft",
            "publish",
            "social media",
            "blog",
            "newsletter",
            "seo",
            "tone adjust",
            "proofread",
            "headline",
            "copywrite",
            "generate ad",
            "a b test copy",
            "content calendar",
            "keyword research",
            "meta description",
            "alt text",
            "repurpose",
            "localize",
            "transcribe",
            "voiceover",
        ],
        "medium": ["create", "edit", "format", "translate", "summarize", "rewrite"],
    },
    "HEALTHCARE": {
        "high": [
            "diagnosis",
            "symptom",
            "medication",
            "dosage",
            "patient",
            "ehr",
            "icd code",
            "clinical",
            "triage",
            "lab result",
            "prescription",
            "contraindication",
            "allergy",
            "vitals",
            "fhir",
            "snomed",
            "loinc",
            "cpt code",
            "prior auth",
            "care plan",
            "referral",
            "discharge summary",
            "radiology",
            "pathology",
            "drug interaction",
        ],
        "medium": ["check", "review", "flag", "notify", "lookup", "search", "validate"],
    },
    "LEGAL": {
        "high": [
            "extract clause",
            "flag risk",
            "compare document",
            "cite precedent",
            "contract review",
            "due diligence",
            "redline",
            "negotiate term",
            "identify obligation",
            "check jurisdiction",
            "statute lookup",
            "case law",
            "compliance check",
            "gdpr",
            "hipaa",
            "sox",
            "nda",
            "liability",
            "indemnity",
            "arbitration",
            "governing law",
            "amendment",
            "termination clause",
            "ip assignment",
            "force majeure",
        ],
        "medium": [
            "review",
            "flag",
            "validate",
            "extract",
            "compare",
            "summarize",
            "annotate",
        ],
    },
    "HR_RECRUITING": {
        "high": [
            "parse resume",
            "score candidate",
            "schedule interview",
            "send offer",
            "background check",
            "skills match",
            "job description",
            "ats",
            "applicant",
            "screen candidate",
            "rank applicant",
            "send rejection",
            "onboarding",
            "document collection",
            "reference check",
            "salary benchmark",
            "headcount",
            "requisition",
            "diversity flag",
            "bias check",
        ],
        "medium": ["search", "filter", "rank", "assign", "notify", "email", "schedule"],
    },
    "DATA_ANALYSIS": {
        "high": [
            "run query",
            "generate chart",
            "export csv",
            "calculate metric",
            "sql",
            "aggregate",
            "pivot",
            "join table",
            "filter rows",
            "group by",
            "window function",
            "create dashboard",
            "visualize",
            "correlation",
            "regression",
            "forecast",
            "anomaly detect",
            "describe data",
            "profile dataset",
            "validate schema",
            "data quality",
        ],
        "medium": ["fetch", "load", "parse", "transform", "format", "sort", "merge"],
    },
    "ECOMMERCE_SALES": {
        "high": [
            "recommend product",
            "check inventory",
            "apply discount",
            "process order",
            "upsell",
            "cross sell",
            "cart",
            "checkout",
            "product search",
            "price lookup",
            "shipping estimate",
            "return request",
            "loyalty points",
            "coupon",
            "abandoned cart",
            "wishlist",
            "review sentiment",
            "stock alert",
            "bundle",
            "dynamic pricing",
        ],
        "medium": ["search", "filter", "lookup", "notify", "update", "create", "fetch"],
    },
    "SECURITY_ITOPS": {
        "high": [
            "scan port",
            "check cve",
            "parse log",
            "block ip",
            "create incident",
            "vulnerability scan",
            "threat intel",
            "firewall rule",
            "intrusion detect",
            "siem",
            "alert triage",
            "malware scan",
            "patch status",
            "access review",
            "privilege escalation",
            "pentest",
            "shodan",
            "virustotal",
            "mitre attack",
            "ioc",
            "quarantine",
            "forensics",
            "network trace",
            "dns lookup",
            "whois",
        ],
        "medium": [
            "check",
            "scan",
            "validate",
            "flag",
            "block",
            "review",
            "query",
            "lookup",
        ],
    },
    "DEVOPS_SRE": {
        "high": [
            "check metrics",
            "rollback deploy",
            "scale service",
            "page oncall",
            "restart service",
            "deploy",
            "canary",
            "feature flag",
            "health check",
            "log query",
            "alert rule",
            "incident",
            "runbook",
            "postmortem",
            "slo",
            "sli",
            "error budget",
            "prometheus",
            "grafana",
            "datadog",
            "pagerduty",
            "kubernetes",
            "helm",
            "terraform",
            "ansible",
        ],
        "medium": [
            "check",
            "monitor",
            "update",
            "restart",
            "scale",
            "deploy",
            "notify",
            "rollback",
        ],
    },
    "GENERAL": {
        "high": [],
        "medium": [],
    },
}

# Preset dimension weights for each use case (sum to 1.0)
# Now includes 12 dimensions: 9 original + time_to_first_tool + semantic_drift + tool_sequence_transitions
USE_CASE_WEIGHTS = {
    "FINANCIAL": {
        "decision_drift": 0.30,
        "error_rate": 0.18,
        "tool_sequence": 0.15,
        "latency": 0.10,
        "semantic_drift": 0.08,
        "tool_sequence_transitions": 0.05,
        "tool_distribution": 0.05,
        "loop_depth": 0.04,
        "time_to_first_tool": 0.02,
        "verbosity_ratio": 0.01,
        "retry_rate": 0.01,
        "output_length": 0.01,
    },
    "CUSTOMER_SUPPORT": {
        "decision_drift": 0.26,
        "tool_sequence": 0.14,
        "error_rate": 0.13,
        "latency": 0.11,
        "semantic_drift": 0.10,
        "tool_distribution": 0.09,
        "tool_sequence_transitions": 0.06,
        "retry_rate": 0.05,
        "time_to_first_tool": 0.04,
        "loop_depth": 0.01,
        "verbosity_ratio": 0.01,
        "output_length": 0.00,
    },
    "RESEARCH_RAG": {
        "output_length": 0.22,
        "verbosity_ratio": 0.16,
        "tool_sequence": 0.16,
        "tool_distribution": 0.13,
        "semantic_drift": 0.12,
        "decision_drift": 0.09,
        "latency": 0.05,
        "tool_sequence_transitions": 0.04,
        "error_rate": 0.02,
        "time_to_first_tool": 0.01,
        "loop_depth": 0.00,
        "retry_rate": 0.00,
    },
    "CODE_GENERATION": {
        "error_rate": 0.28,
        "tool_sequence": 0.17,
        "loop_depth": 0.13,
        "retry_rate": 0.10,
        "decision_drift": 0.09,
        "tool_sequence_transitions": 0.08,
        "latency": 0.05,
        "semantic_drift": 0.04,
        "tool_distribution": 0.03,
        "time_to_first_tool": 0.01,
        "verbosity_ratio": 0.01,
        "output_length": 0.01,
    },
    "AUTOMATION": {
        "error_rate": 0.22,
        "tool_sequence": 0.17,
        "retry_rate": 0.17,
        "latency": 0.10,
        "decision_drift": 0.09,
        "tool_sequence_transitions": 0.08,
        "time_to_first_tool": 0.05,
        "semantic_drift": 0.04,
        "loop_depth": 0.03,
        "tool_distribution": 0.03,
        "verbosity_ratio": 0.01,
        "output_length": 0.01,
    },
    "CONTENT_GENERATION": {
        "output_length": 0.26,
        "verbosity_ratio": 0.21,
        "decision_drift": 0.18,
        "tool_distribution": 0.09,
        "semantic_drift": 0.08,
        "latency": 0.05,
        "tool_sequence": 0.05,
        "error_rate": 0.03,
        "tool_sequence_transitions": 0.02,
        "time_to_first_tool": 0.01,
        "loop_depth": 0.01,
        "retry_rate": 0.01,
    },
    "HEALTHCARE": {
        "decision_drift": 0.34,
        "error_rate": 0.22,
        "tool_sequence": 0.13,
        "semantic_drift": 0.10,
        "latency": 0.07,
        "tool_sequence_transitions": 0.06,
        "tool_distribution": 0.04,
        "retry_rate": 0.02,
        "time_to_first_tool": 0.01,
        "loop_depth": 0.01,
        "verbosity_ratio": 0.00,
        "output_length": 0.00,
    },
    "LEGAL": {
        "decision_drift": 0.33,
        "error_rate": 0.20,
        "tool_sequence": 0.15,
        "semantic_drift": 0.08,
        "latency": 0.07,
        "tool_sequence_transitions": 0.05,
        "tool_distribution": 0.04,
        "loop_depth": 0.03,
        "time_to_first_tool": 0.02,
        "verbosity_ratio": 0.01,
        "retry_rate": 0.01,
        "output_length": 0.01,
    },
    "HR_RECRUITING": {
        "decision_drift": 0.28,
        "tool_sequence": 0.15,
        "error_rate": 0.13,
        "latency": 0.09,
        "tool_distribution": 0.09,
        "semantic_drift": 0.08,
        "tool_sequence_transitions": 0.05,
        "output_length": 0.05,
        "verbosity_ratio": 0.03,
        "time_to_first_tool": 0.03,
        "retry_rate": 0.02,
        "loop_depth": 0.00,
    },
    "DATA_ANALYSIS": {
        "tool_sequence": 0.21,
        "error_rate": 0.23,
        "decision_drift": 0.16,
        "output_length": 0.08,
        "tool_sequence_transitions": 0.07,
        "tool_distribution": 0.07,
        "semantic_drift": 0.06,
        "latency": 0.05,
        "loop_depth": 0.03,
        "time_to_first_tool": 0.02,
        "retry_rate": 0.01,
        "verbosity_ratio": 0.01,
    },
    "ECOMMERCE_SALES": {
        "decision_drift": 0.23,
        "tool_sequence": 0.17,
        "latency": 0.10,
        "error_rate": 0.13,
        "time_to_first_tool": 0.08,
        "tool_distribution": 0.07,
        "semantic_drift": 0.06,
        "tool_sequence_transitions": 0.05,
        "retry_rate": 0.04,
        "output_length": 0.04,
        "loop_depth": 0.02,
        "verbosity_ratio": 0.01,
    },
    "SECURITY_ITOPS": {
        "decision_drift": 0.30,
        "error_rate": 0.22,
        "tool_sequence": 0.15,
        "retry_rate": 0.07,
        "semantic_drift": 0.06,
        "tool_sequence_transitions": 0.05,
        "latency": 0.04,
        "time_to_first_tool": 0.04,
        "tool_distribution": 0.04,
        "loop_depth": 0.02,
        "verbosity_ratio": 0.01,
        "output_length": 0.00,
    },
    "DEVOPS_SRE": {
        "tool_sequence": 0.22,
        "decision_drift": 0.23,
        "error_rate": 0.16,
        "latency": 0.04,
        "tool_sequence_transitions": 0.08,
        "time_to_first_tool": 0.06,
        "retry_rate": 0.06,
        "semantic_drift": 0.05,
        "tool_distribution": 0.04,
        "loop_depth": 0.03,
        "verbosity_ratio": 0.02,
        "output_length": 0.01,
    },
    "GENERAL": {
        "decision_drift": 0.091,
        "tool_sequence": 0.0909,
        "latency": 0.0909,
        "tool_distribution": 0.0909,
        "error_rate": 0.0909,
        "loop_depth": 0.0909,
        "verbosity_ratio": 0.0909,
        "retry_rate": 0.0909,
        "output_length": 0.0909,
        "time_to_first_tool": 0.0909,
        "semantic_drift": 0.0909,
        "tool_sequence_transitions": 0.000,
    },
}


def _normalize_tool_name(name: str) -> str:
    """Normalize tool name: lowercase, replace hyphens/underscores with spaces."""
    return name.lower().replace("-", " ").replace("_", " ").strip()


def infer_use_case(tool_names: list[str]) -> dict:
    """
    Infer agent use case from tool names using keyword scoring.

    Args:
        tool_names: List of unique tool names observed for this agent

    Returns:
        {
            "use_case": str,           # e.g. "FINANCIAL"
            "confidence": float,       # 0.0 - 1.0
            "matched_keywords": list[str],
            "scores": dict[str, float] # all category scores, for debugging
        }
    """
    try:
        # Normalize all tool names
        normalized_tools = [_normalize_tool_name(name) for name in tool_names]

        # Score each category
        scores = {}
        matched_keywords_per_category = {}

        for category, keywords in USE_CASE_KEYWORDS.items():
            score = 0.0
            matched = []

            # Check high-signal keywords (weight × 2)
            for keyword in keywords["high"]:
                for tool in normalized_tools:
                    if keyword in tool:
                        score += 2.0
                        matched.append(keyword)
                        break  # Only count each keyword once per category

            # Check medium-signal keywords (weight × 1)
            for keyword in keywords["medium"]:
                for tool in normalized_tools:
                    if keyword in tool:
                        score += 1.0
                        matched.append(keyword)
                        break

            scores[category] = score
            matched_keywords_per_category[category] = matched

        # Find winner and second place
        sorted_scores = sorted(scores.items(), key=lambda x: x[1], reverse=True)

        if not sorted_scores or sorted_scores[0][1] < 3.0:
            # No category scored enough - fall back to GENERAL
            return {
                "use_case": "GENERAL",
                "confidence": 0.0,
                "matched_keywords": [],
                "scores": scores,
            }

        winner = sorted_scores[0]
        winner_category = winner[0]
        winner_score = winner[1]

        # Calculate confidence
        if len(sorted_scores) < 2 or sorted_scores[1][1] == 0:
            confidence = 1.0
        else:
            second_score = sorted_scores[1][1]
            confidence = winner_score / (winner_score + second_score)
            confidence = min(1.0, max(0.0, confidence))

        return {
            "use_case": winner_category,
            "confidence": confidence,
            "matched_keywords": matched_keywords_per_category[winner_category],
            "scores": scores,
        }

    except Exception as e:
        logger.debug(f"Use case inference failed: {e}")
        # Never raise - degrade gracefully to GENERAL
        return {
            "use_case": "GENERAL",
            "confidence": 0.0,
            "matched_keywords": [],
            "scores": {},
        }
