"""
Use case inference from tool names.

Infers agent use case from observed tool names using keyword scoring.
Returns inferred category with confidence score for dimension weight calibration.
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

COMPATIBLE_USE_CASE_PAIRS = {
    frozenset({"AUTOMATION", "CODE_GENERATION"}),
    frozenset({"AUTOMATION", "DEVOPS_SRE"}),
    frozenset({"AUTOMATION", "DATA_ANALYSIS"}),
    frozenset({"RESEARCH_RAG", "DATA_ANALYSIS"}),
    frozenset({"RESEARCH_RAG", "CONTENT_GENERATION"}),
    frozenset({"CUSTOMER_SUPPORT", "ECOMMERCE_SALES"}),
    frozenset({"SECURITY_ITOPS", "DEVOPS_SRE"}),
    frozenset({"FINANCIAL", "LEGAL"}),
    frozenset({"HEALTHCARE", "LEGAL"}),
    frozenset({"HR_RECRUITING", "CUSTOMER_SUPPORT"}),
    frozenset({"DATA_ANALYSIS", "CONTENT_GENERATION"}),
}

GENERIC_SINGLE_WORDS = {
    "tool",
    "action",
    "handler",
    "worker",
    "job",
    "task",
    "step",
    "node",
    "stage",
    "pipeline",
    "process",
    "execute",
    "run",
    "call",
    "invoke",
    "trigger",
    "dispatch",
    "emit",
    "fire",
    "main",
    "entry",
    "function",
    "method",
    "operation",
    "command",
    "request",
    "response",
}

ABBREVIATION_EXPANSIONS = {
    "proc": "process",
    "chk": "check",
    "upd": "update",
    "del": "delete",
    "ins": "insert",
    "calc": "calculate",
    "auth": "authenticate",
    "val": "validate",
    "verif": "verify",
    "mgmt": "management",
    "svc": "service",
    "cfg": "config",
    "msg": "message",
    "notif": "notification",
    "err": "error",
    "req": "request",
    "resp": "response",
    "usr": "user",
    "acct": "account",
    "txn": "transaction",
    "pmt": "payment",
    "inv": "invoice",
    "ord": "order",
    "prod": "product",
    "cust": "customer",
    "doc": "document",
    "img": "image",
    "vid": "video",
    "rbac": "role",
    "iam": "access",
    "k8s": "kubernetes",
    "infra": "infrastructure",
    "db": "database",
    "repo": "repository",
    "env": "environment",
    "dep": "deployment",
    "sec": "security",
    "vuln": "vulnerability",
    "cve": "cve",  # Keep as-is, it's a known keyword
    "scan": "scan",
    "ml": "model",
    "ai": "model",
    "llm": "model",
    "rag": "retrieval",
    "vec": "vector",
    "emb": "embedding",
}

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
            # Spanish
            "pago",
            "credito",
            "fraude",
            "factura",
            "transferencia",
            "cuenta",
            "prestamo",
            "riesgo",
            "aprobacion",
            "rechazo",
            # French
            "paiement",
            "credit",
            "fraude",
            "facture",
            "virement",
            "compte",
            "pret",
            "risque",
            "approbation",
            "rejet",
            # German
            "zahlung",
            "kredit",
            "betrug",
            "rechnung",
            "überweisung",
            "konto",
            "darlehen",
            "risiko",
            "genehmigung",
            "ablehnung",
            # Dutch
            "betaling",
            "krediet",
            "fraude",
            "factuur",
            "overboeking",
            "rekening",
            "lening",
            "risico",
            "goedkeuring",
            "afwijzing",
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
            # Spanish
            "ticket",
            "escalar",
            "resolver",
            "queja",
            "satisfaccion",
            # French
            "ticket",
            "escalade",
            "resoudre",
            "plainte",
            "satisfaction",
            # German
            "ticket",
            "eskalieren",
            "lösen",
            "beschwerde",
            "zufriedenheit",
            # Dutch
            "ticket",
            "escaleren",
            "oplossen",
            "klacht",
            "tevredenheid",
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
            # Spanish
            "diagnostico",
            "paciente",
            "medicamento",
            "dosis",
            "sintoma",
            # French
            "diagnostic",
            "patient",
            "medicament",
            "dose",
            "symptome",
            # German
            "diagnose",
            "patient",
            "medikament",
            "dosis",
            "symptom",
            # Dutch
            "diagnose",
            "patient",
            "medicijn",
            "dosering",
            "symptoom",
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
            # Spanish
            "contrato",
            "clausula",
            "cumplimiento",
            "obligacion",
            "jurisdiccion",
            # French
            "contrat",
            "clause",
            "conformite",
            "obligation",
            "juridiction",
            # German
            "vertrag",
            "klausel",
            "compliance",
            "verpflichtung",
            "zuständigkeit",
            # Dutch
            "contract",
            "clausule",
            "naleving",
            "verplichting",
            "jurisdictie",
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
            # Spanish
            "pedido",
            "producto",
            "carrito",
            "descuento",
            "inventario",
            # French
            "commande",
            "produit",
            "panier",
            "remise",
            "inventaire",
            # German
            "bestellung",
            "produkt",
            "warenkorb",
            "rabatt",
            "inventar",
            # Dutch
            "bestelling",
            "product",
            "winkelwagen",
            "korting",
            "voorraad",
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
        "decision_drift": 0.22,
        "error_rate": 0.18,
        "tool_sequence": 0.16,
        "latency": 0.12,
        "tool_distribution": 0.10,
        "loop_depth": 0.08,
        "retry_rate": 0.06,
        "semantic_drift": 0.04,
        "verbosity_ratio": 0.02,
        "output_length": 0.02,
        "time_to_first_tool": 0.0,
        "tool_sequence_transitions": 0.0,
    },
}


BEHAVIORAL_RULES = {
    "CUSTOMER_SUPPORT": {
        "escalation_rate": ("> 0.15", 5),
        "resolution_rate": ("> 0.60", 4),
        "avg_tool_count": ("< 6", 3),
        "avg_latency_p95": ("< 3000", 2),
    },
    "CODE_GENERATION": {
        "avg_loop_depth": ("> 3", 5),
        "avg_tool_count": ("> 8", 4),
        "avg_output_length": ("> 500", 3),
        "avg_latency_p95": ("> 4000", 2),
    },
    "RESEARCH_RAG": {
        "avg_output_length": ("> 800", 5),
        "avg_tool_count": ("> 6", 4),
        "avg_latency_p95": ("> 3000", 3),
        "avg_verbosity_ratio": ("> 0.6", 2),
    },
    "CONTENT_GENERATION": {
        "avg_output_length": ("> 600", 5),
        "avg_verbosity_ratio": ("> 0.7", 4),
        "avg_tool_count": ("< 4", 3),
    },
    "DATA_ANALYSIS": {
        "avg_tool_count": ("> 6", 5),
        "avg_latency_p95": ("> 3000", 4),
        "avg_loop_depth": ("> 2", 3),
        "error_rate": ("< 0.05", 2),
    },
    "WORKFLOW_ORCHESTRATION": {
        "avg_loop_depth": ("> 4", 5),
        "avg_retry_rate": ("> 0.10", 4),
        "avg_tool_count": ("> 10", 3),
        "error_rate": ("> 0.05", 2),
    },
    "REAL_TIME_MONITORING": {
        "avg_latency_p95": ("< 2000", 5),
        "avg_time_to_first_tool": ("< 500", 4),
        "avg_tool_count": ("< 5", 3),
        "avg_loop_depth": ("< 2", 2),
    },
    "TESTING_VALIDATION": {
        "error_rate": ("> 0.10", 5),
        "avg_retry_rate": ("> 0.15", 4),
        "avg_loop_depth": ("> 3", 3),
        "fallback_rate": ("> 0.10", 2),
    },
    "DEBUGGING_TROUBLESHOOTING": {
        "avg_retry_rate": ("> 0.20", 5),
        "error_rate": ("> 0.15", 4),
        "avg_loop_depth": ("> 4", 3),
        "fallback_rate": ("> 0.15", 2),
    },
    "DECISION_SUPPORT": {
        "avg_output_length": ("> 400", 4),
        "avg_verbosity_ratio": ("> 0.5", 3),
        "avg_tool_count": ("> 4", 3),
        "avg_latency_p95": ("> 2500", 2),
    },
    "TASK_AUTOMATION": {
        "avg_loop_depth": ("> 2", 4),
        "avg_tool_count": ("> 5", 4),
        "avg_retry_rate": ("< 0.05", 3),
        "error_rate": ("< 0.05", 2),
    },
    "SYNTHETIC_DATA_GENERATION": {
        "avg_output_length": ("> 500", 5),
        "avg_tool_count": ("< 3", 4),
        "avg_verbosity_ratio": ("> 0.65", 3),
    },
    "AGENT_ORCHESTRATION": {
        "avg_loop_depth": ("> 5", 5),
        "avg_tool_count": ("> 12", 4),
        "avg_retry_rate": ("> 0.10", 3),
        "avg_latency_p95": ("> 5000", 2),
    },
}

UNIFORM_AGENT_BEHAVIORAL_RULES = {
    "FINANCIAL": [
        (
            lambda s: (
                s.get("error_rate", 1.0) < 0.02
                and s.get("escalation_rate", 1.0) < 0.10
                and 3 <= s.get("avg_tool_count", 0) <= 8
            ),
            3,
        ),
    ],
    "CONTENT_GENERATION": [
        (
            lambda s: (
                s.get("avg_output_length", 0) > 400
                and s.get("avg_tool_count", 100) < 4
                and s.get("error_rate", 1.0) < 0.05
            ),
            3,
        ),
    ],
    "DATA_ANALYSIS": [
        (
            lambda s: (
                s.get("avg_tool_count", 0) > 5
                and s.get("escalation_rate", 1.0) < 0.05
                and s.get("avg_output_length", 0) > 300
            ),
            3,
        ),
    ],
    "DEVOPS_SRE": [
        (
            lambda s: (
                s.get("avg_tool_count", 0) > 5
                and s.get("avg_latency_p95", 0) > 4000
                and s.get("escalation_rate", 1.0) < 0.05
            ),
            3,
        ),
    ],
    "HEALTHCARE": [
        (
            lambda s: (
                s.get("error_rate", 1.0) < 0.01
                and 2 <= s.get("avg_tool_count", 0) <= 6
                and s.get("avg_time_to_first_tool", 0) > 800
            ),
            3,
        ),
    ],
}


def _are_compatible(use_case_a: str, use_case_b: str) -> bool:
    """
    Returns True if two use cases can be meaningfully blended.
    GENERAL is always compatible with everything.
    Same use case is always compatible with itself.
    """
    if use_case_a == "GENERAL" or use_case_b == "GENERAL":
        return True
    if use_case_a == use_case_b:
        return True
    return frozenset({use_case_a, use_case_b}) in COMPATIBLE_USE_CASE_PAIRS


def _extract_behavioral_signals(runs: list[dict]) -> dict[str, float]:
    """
    Extract behavioral signals from runs.

    Returns dict with keys:
    - escalation_rate, resolution_rate, error_rate, fallback_rate
    - avg_loop_depth, avg_tool_count, avg_output_length
    - avg_verbosity_ratio, avg_retry_rate, avg_latency_p95, avg_time_to_first_tool
    """
    if not runs:
        return {}

    import numpy as np

    escalation_count = sum(1 for r in runs if r.get("error_count", 0) > 0)
    resolution_count = sum(1 for r in runs if r.get("error_count", 0) == 0)
    fallback_count = sum(1 for r in runs if r.get("retry_count", 0) > 2)

    n = len(runs)
    escalation_rate = escalation_count / n if n > 0 else 0.0
    resolution_rate = resolution_count / n if n > 0 else 0.0
    error_rate = sum(r.get("error_count", 0) for r in runs) / n if n > 0 else 0.0
    fallback_rate = fallback_count / n if n > 0 else 0.0

    loop_depths = [r.get("loop_count", 0) for r in runs]
    tool_counts = [r.get("tool_call_count", 0) for r in runs]
    output_lengths = [r.get("output_length", 0) for r in runs]
    verbosity_ratios = [r.get("verbosity_ratio", 0.0) for r in runs]
    retry_rates = [r.get("retry_count", 0) for r in runs]
    latencies = [r.get("latency_ms", 0) for r in runs if r.get("latency_ms", 0) > 0]
    time_to_first_tools = [
        r.get("time_to_first_tool_ms", 0)
        for r in runs
        if r.get("time_to_first_tool_ms", 0) > 0
    ]

    signals = {
        "escalation_rate": escalation_rate,
        "resolution_rate": resolution_rate,
        "error_rate": error_rate,
        "fallback_rate": fallback_rate,
        "avg_loop_depth": float(np.mean(loop_depths)) if loop_depths else 0.0,
        "avg_tool_count": float(np.mean(tool_counts)) if tool_counts else 0.0,
        "avg_output_length": float(np.mean(output_lengths)) if output_lengths else 0.0,
        "avg_verbosity_ratio": (
            float(np.mean(verbosity_ratios)) if verbosity_ratios else 0.0
        ),
        "avg_retry_rate": float(np.mean(retry_rates)) if retry_rates else 0.0,
        "avg_latency_p95": (
            float(np.percentile(latencies, 95)) if len(latencies) > 0 else 0.0
        ),
        "avg_time_to_first_tool": (
            float(np.mean(time_to_first_tools)) if time_to_first_tools else 0.0
        ),
    }

    return signals


def _evaluate_rule(signal_value: float, rule_str: str) -> bool:
    """Evaluate a single behavioral rule (e.g., '> 0.15', '< 3000')."""
    try:
        parts = rule_str.split()
        if len(parts) != 2:
            return False
        operator, threshold_str = parts
        threshold = float(threshold_str)

        if operator == ">":
            return signal_value > threshold
        elif operator == "<":
            return signal_value < threshold
        elif operator == ">=":
            return signal_value >= threshold
        elif operator == "<=":
            return signal_value <= threshold
        else:
            return False
    except Exception:
        return False


def infer_use_case_from_behavior(runs: list[dict]) -> dict:
    """
    Infer use case from behavioral signals (escalation, latency, loop depth, etc).

    Works even when tool names are completely generic. Fires only when n_runs >= 5.

    Args:
        runs: List of run dicts from get_runs()

    Returns:
        {
            "use_case": str,
            "confidence": float,
            "behavioral_signals": dict,
            "scores": dict[str, float]
        }
    """
    try:
        # Minimum data requirement
        if len(runs) < 5:
            return {
                "use_case": "GENERAL",
                "confidence": 0.0,
                "behavioral_signals": {},
                "scores": {},
            }

        signals = _extract_behavioral_signals(runs)
        if not signals:
            return {
                "use_case": "GENERAL",
                "confidence": 0.0,
                "behavioral_signals": {},
                "scores": {},
            }

        # Score each use case
        scores = {}
        for use_case, rules in BEHAVIORAL_RULES.items():
            score = 0.0
            for signal_name, (rule_str, weight) in rules.items():
                signal_value = signals.get(signal_name, 0.0)
                if _evaluate_rule(signal_value, rule_str):
                    score += weight
            scores[use_case] = score

        # Add GENERAL as fallback
        scores["GENERAL"] = 1.0

        # Check if all scores are below threshold (well-behaved agent)
        max_primary_score = max(s for uc, s in scores.items() if uc != "GENERAL")
        if max_primary_score < 2:
            # Apply uniform agent rules as fallback
            for use_case, rules in UNIFORM_AGENT_BEHAVIORAL_RULES.items():
                uniform_score = 0.0
                for rule_func, weight in rules:
                    try:
                        if rule_func(signals):
                            uniform_score += weight
                    except Exception as e:
                        logger.debug(
                            f"Uniform rule evaluation failed for {use_case}: {e}"
                        )
                if uniform_score > 0:
                    scores[use_case] = scores.get(use_case, 0.0) + uniform_score

        # Find winner
        sorted_scores = sorted(scores.items(), key=lambda x: x[1], reverse=True)
        winner, winner_score = sorted_scores[0]
        second_place_score = sorted_scores[1][1] if len(sorted_scores) > 1 else 0.0

        # Minimum score threshold
        if winner_score < 2:
            winner = "GENERAL"
            confidence = 0.0
        else:
            # Confidence formula: winner_score / (winner_score + second_place_score)
            confidence = (
                winner_score / (winner_score + second_place_score)
                if (winner_score + second_place_score) > 0
                else 0.0
            )

        return {
            "use_case": winner,
            "confidence": confidence,
            "behavioral_signals": signals,
            "scores": scores,
        }

    except Exception as e:
        logger.debug(f"Behavioral inference failed: {e}")
        # Never raise
        return {
            "use_case": "GENERAL",
            "confidence": 0.0,
            "behavioral_signals": {},
            "scores": {},
        }


def blend_inferences(
    keyword_result: dict,
    behavioral_result: dict,
) -> dict:
    """
    Blend keyword and behavioral inferences proportionally by confidence.

    Args:
        keyword_result: Result from infer_use_case()
        behavioral_result: Result from infer_use_case_from_behavior()

    Returns:
        {
            "use_case": str (final use case - one of the inputs or GENERAL),
            "blended_weights": dict[str, float] (sum to 1.0),
            "blend_method": str ("keyword_dominant" | "behavioral_dominant" | "blended" | "general_fallback"),
            "keyword_use_case": str,
            "keyword_confidence": float,
            "behavioral_use_case": str,
            "behavioral_confidence": float,
            "behavioral_signals": dict,
        }

    Never raises - always returns valid weights that sum to 1.0.
    """
    try:
        kw_use_case = keyword_result.get("use_case", "GENERAL")
        kw_conf = keyword_result.get("confidence", 0.0)
        beh_use_case = behavioral_result.get("use_case", "GENERAL")
        beh_conf = behavioral_result.get("confidence", 0.0)
        beh_signals = behavioral_result.get("behavioral_signals", {})

        # Clamp confidences to [0, 1]
        kw_conf = max(0.0, min(1.0, kw_conf))
        beh_conf = max(0.0, min(1.0, beh_conf))

        # Confidence floor: if keyword score is below threshold but behavioral agrees
        if (
            kw_use_case != "GENERAL"
            and kw_use_case == beh_use_case
            and kw_conf > 0
            and beh_conf >= 0.3
        ):
            kw_conf = max(kw_conf, 0.5)

        # If both are GENERAL with 0 confidence, return GENERAL fallback
        if kw_use_case == "GENERAL" and beh_use_case == "GENERAL":
            if kw_conf == 0.0 and beh_conf == 0.0:
                return {
                    "use_case": "GENERAL",
                    "blended_weights": USE_CASE_WEIGHTS["GENERAL"].copy(),
                    "blend_method": "general_fallback",
                    "keyword_use_case": kw_use_case,
                    "keyword_confidence": kw_conf,
                    "behavioral_use_case": beh_use_case,
                    "behavioral_confidence": beh_conf,
                    "behavioral_signals": beh_signals,
                    "conflict_detected": False,
                    "conflict_winner": "",
                }

        # Check for conflict: incompatible use cases
        if not _are_compatible(kw_use_case, beh_use_case):
            # Take higher confidence classifier, blend with GENERAL
            if kw_conf >= beh_conf:
                winner_use_case = kw_use_case
                winner_conf = kw_conf
                loser_use_case = beh_use_case
            else:
                winner_use_case = beh_use_case
                winner_conf = beh_conf
                loser_use_case = kw_use_case

            winner_weights = USE_CASE_WEIGHTS.get(
                winner_use_case, USE_CASE_WEIGHTS["GENERAL"]
            )
            gen_weights = USE_CASE_WEIGHTS["GENERAL"]
            gen_conf = 1.0 - winner_conf

            blended = {
                dim: winner_conf * winner_weights.get(dim, 0.0)
                + gen_conf * gen_weights.get(dim, 0.0)
                for dim in winner_weights
            }

            total = sum(blended.values())
            if total > 0:
                blended = {dim: w / total for dim, w in blended.items()}
            else:
                blended = gen_weights.copy()

            return {
                "use_case": winner_use_case,
                "blended_weights": blended,
                "blend_method": "conflict_resolved",
                "keyword_use_case": kw_use_case,
                "keyword_confidence": kw_conf,
                "behavioral_use_case": beh_use_case,
                "behavioral_confidence": beh_conf,
                "behavioral_signals": beh_signals,
                "conflict_detected": True,
                "conflict_winner": winner_use_case,
                "conflict_loser": loser_use_case,
            }

        # Normalize confidences so kw_conf + beh_conf + gen_conf = 1.0
        total_conf = kw_conf + beh_conf
        if total_conf > 0:
            kw_norm = kw_conf / total_conf
            beh_norm = beh_conf / total_conf
            gen_norm = 0.0
        else:
            # Both are 0 but not both GENERAL - shouldn't happen, fall back
            kw_norm = 0.0
            beh_norm = 0.0
            gen_norm = 1.0

        # Get weights for each classifier
        kw_weights = USE_CASE_WEIGHTS.get(kw_use_case, USE_CASE_WEIGHTS["GENERAL"])
        beh_weights = USE_CASE_WEIGHTS.get(beh_use_case, USE_CASE_WEIGHTS["GENERAL"])
        gen_weights = USE_CASE_WEIGHTS["GENERAL"]

        # Blend weights
        blended = {}
        for dim in gen_weights:
            kw_w = kw_weights.get(dim, 0.0)
            beh_w = beh_weights.get(dim, 0.0)
            gen_w = gen_weights.get(dim, 0.0)
            blended[dim] = kw_norm * kw_w + beh_norm * beh_w + gen_norm * gen_w

        # Renormalize to exactly 1.0
        total = sum(blended.values())
        if total > 0:
            blended = {dim: w / total for dim, w in blended.items()}
        else:
            # Should never happen, but fallback to GENERAL
            blended = gen_weights.copy()

        # Determine blend method and final use case
        if kw_conf > beh_conf * 1.5:
            blend_method = "keyword_dominant"
            final_use_case = kw_use_case
        elif beh_conf > kw_conf * 1.5:
            blend_method = "behavioral_dominant"
            final_use_case = beh_use_case
        elif kw_conf > 0.1 or beh_conf > 0.1:
            blend_method = "blended"
            # Use higher confidence classifier's use case
            final_use_case = kw_use_case if kw_conf >= beh_conf else beh_use_case
        else:
            blend_method = "general_fallback"
            final_use_case = "GENERAL"

        # Sanity check: weights must sum to ~1.0
        weight_sum = sum(blended.values())
        assert abs(weight_sum - 1.0) < 0.01, f"Blended weights sum to {weight_sum}"

        return {
            "use_case": final_use_case,
            "blended_weights": blended,
            "blend_method": blend_method,
            "keyword_use_case": kw_use_case,
            "keyword_confidence": kw_conf,
            "behavioral_use_case": beh_use_case,
            "behavioral_confidence": beh_conf,
            "behavioral_signals": beh_signals,
            "conflict_detected": False,
            "conflict_winner": "",
        }

    except Exception as e:
        logger.debug(f"Blend inference failed: {e}")
        # Never raise - return GENERAL as fallback
        return {
            "use_case": "GENERAL",
            "blended_weights": USE_CASE_WEIGHTS["GENERAL"].copy(),
            "blend_method": "general_fallback",
            "keyword_use_case": "GENERAL",
            "keyword_confidence": 0.0,
            "behavioral_use_case": "GENERAL",
            "behavioral_confidence": 0.0,
            "behavioral_signals": {},
            "conflict_detected": False,
            "conflict_winner": "",
        }


GENERIC_PATTERN_SCORES = {
    "prefixes": {
        "search_": {"RESEARCH_RAG": 1, "ECOMMERCE_SALES": 1},
        "get_": {},
        "fetch_": {"RESEARCH_RAG": 1},
        "query_": {"DATA_ANALYSIS": 1, "RESEARCH_RAG": 1},
        "run_": {"AUTOMATION": 1, "CODE_GENERATION": 1},
        "execute_": {"AUTOMATION": 1, "CODE_GENERATION": 1},
        "call_": {"AUTOMATION": 1},
        "process_": {"AUTOMATION": 1},
        "send_": {"AUTOMATION": 1, "CUSTOMER_SUPPORT": 1},
        "create_": {"AUTOMATION": 1},
        "update_": {"AUTOMATION": 1},
        "delete_": {"AUTOMATION": 1},
        "check_": {"SECURITY_ITOPS": 1, "DEVOPS_SRE": 1},
        "validate_": {"FINANCIAL": 1, "LEGAL": 1, "HEALTHCARE": 1},
        "verify_": {"FINANCIAL": 1, "LEGAL": 1},
        "analyze_": {"DATA_ANALYSIS": 1},
        "generate_": {"CONTENT_GENERATION": 1, "CODE_GENERATION": 1},
        "extract_": {"RESEARCH_RAG": 1, "LEGAL": 1},
        "parse_": {"DATA_ANALYSIS": 1, "AUTOMATION": 1},
        "monitor_": {"DEVOPS_SRE": 1, "SECURITY_ITOPS": 1},
        "deploy_": {"DEVOPS_SRE": 1},
        "schedule_": {"AUTOMATION": 1},
        "notify_": {"AUTOMATION": 1, "CUSTOMER_SUPPORT": 1},
        "lookup_": {"CUSTOMER_SUPPORT": 1, "ECOMMERCE_SALES": 1},
        "recommend_": {"ECOMMERCE_SALES": 1},
        "classify_": {"SECURITY_ITOPS": 1, "HEALTHCARE": 1},
        "score_": {"FINANCIAL": 1, "HR_RECRUITING": 1},
        "review_": {"LEGAL": 1, "CODE_GENERATION": 1},
        "approve_": {"FINANCIAL": 1, "HR_RECRUITING": 1},
        "reject_": {"FINANCIAL": 1, "HR_RECRUITING": 1},
        "flag_": {"SECURITY_ITOPS": 1, "FINANCIAL": 1},
        "trigger_": {"AUTOMATION": 1, "DEVOPS_SRE": 1},
    },
    "suffixes": {
        "_api": {"AUTOMATION": 1},
        "_tool": {"AUTOMATION": 1},
        "_action": {"AUTOMATION": 1},
        "_handler": {"AUTOMATION": 1},
        "_service": {"DEVOPS_SRE": 1},
        "_check": {"SECURITY_ITOPS": 1, "DEVOPS_SRE": 1},
        "_search": {"RESEARCH_RAG": 1, "ECOMMERCE_SALES": 1},
        "_query": {"DATA_ANALYSIS": 1},
        "_report": {"DATA_ANALYSIS": 1},
        "_alert": {"DEVOPS_SRE": 1, "SECURITY_ITOPS": 1},
        "_event": {"AUTOMATION": 1},
        "_message": {"CUSTOMER_SUPPORT": 1, "AUTOMATION": 1},
        "_email": {"AUTOMATION": 1, "CUSTOMER_SUPPORT": 1},
        "_review": {"LEGAL": 1, "CODE_GENERATION": 1},
        "_analysis": {"DATA_ANALYSIS": 1},
        "_summary": {"RESEARCH_RAG": 1, "CONTENT_GENERATION": 1},
    },
}


def _decompose_tool_name(tool_name: str) -> list[str]:
    """
    Decompose a tool name into component words for keyword matching.

    Examples:
        "process_order"      → ["process order", "process", "order"]
        "executePayment"     → ["execute payment", "execute", "payment"]
        "runCreditCheck"     → ["run credit check", "run", "credit", "check"]
        "call_fraud_api"     → ["call fraud api", "call", "fraud", "api"]
        "search_knowledge_base" → ["search knowledge base", "search", "knowledge", "base"]
        "run_tool"           → ["run tool", "run", "tool"]

    Returns the full normalized name AND all component words >= 3 characters.
    """
    try:
        if not tool_name:
            return []

        name = tool_name.strip()
        if not name:
            return []

        import re

        name = name.replace("-", "_")
        name_with_underscores = re.sub(r"([a-z])([A-Z])", r"\1_\2", name)
        name_with_underscores = name_with_underscores.lower()

        words = name_with_underscores.split("_")
        words = [w for w in words if len(w) >= 3]

        if not words:
            return []

        # Expand abbreviations
        expanded_words = []
        for word in words:
            expanded = ABBREVIATION_EXPANSIONS.get(word, word)
            expanded_words.append(expanded)

        result = []
        full_normalized = " ".join(expanded_words)
        result.append(full_normalized)
        result.extend(expanded_words)

        return result

    except Exception as e:
        logger.debug(f"Tool name decomposition failed for '{tool_name}': {e}")
        return []


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
        # Decompose all tool names into component words
        all_variants = []
        for name in tool_names:
            variants = _decompose_tool_name(name)
            all_variants.extend(variants)

        # Score each category via keyword matching
        scores = {}
        matched_keywords_per_category = {}
        tool_scored_keyword = {}

        for category, keywords in USE_CASE_KEYWORDS.items():
            score = 0.0
            matched = []

            # Check high-signal keywords (weight × 2)
            for keyword in keywords["high"]:
                for variant in all_variants:
                    if keyword in variant:
                        tool_key = (variant, keyword)
                        if tool_key not in tool_scored_keyword:
                            score += 2.0
                            matched.append(keyword)
                            tool_scored_keyword[tool_key] = True
                        break

            # Check medium-signal keywords (weight × 1)
            for keyword in keywords["medium"]:
                for variant in all_variants:
                    if keyword in variant:
                        tool_key = (variant, keyword)
                        if tool_key not in tool_scored_keyword:
                            score += 1.0
                            matched.append(keyword)
                            tool_scored_keyword[tool_key] = True
                        break

            scores[category] = score
            matched_keywords_per_category[category] = matched

        # Apply generic pattern scoring for zero-scoring tool names
        zero_scored_tools = []
        for name in tool_names:
            decomposed = _decompose_tool_name(name)
            if decomposed:
                full_name = decomposed[0]
                tool_scored_any = any(
                    (variant, kw) in tool_scored_keyword
                    for variant in decomposed
                    for kw in [
                        k
                        for keywords in USE_CASE_KEYWORDS.values()
                        for k in keywords["high"] + keywords["medium"]
                    ]
                )
                if not tool_scored_any:
                    zero_scored_tools.append(full_name.replace(" ", "_"))

        pattern_scores = {}
        for tool_name in zero_scored_tools:
            for prefix, use_cases in GENERIC_PATTERN_SCORES["prefixes"].items():
                if tool_name.startswith(prefix):
                    for use_case, pattern_score in use_cases.items():
                        pattern_scores[use_case] = (
                            pattern_scores.get(use_case, 0) + pattern_score
                        )

            for suffix, use_cases in GENERIC_PATTERN_SCORES["suffixes"].items():
                if tool_name.endswith(suffix):
                    for use_case, pattern_score in use_cases.items():
                        pattern_scores[use_case] = (
                            pattern_scores.get(use_case, 0) + pattern_score
                        )

        for use_case, pattern_score in pattern_scores.items():
            scores[use_case] = scores.get(use_case, 0.0) + pattern_score

        # Check if all tool names are generic single words
        all_generic_single_words = True
        for name in tool_names:
            decomposed = _decompose_tool_name(name)
            if decomposed:
                # Check if any component word is not in GENERIC_SINGLE_WORDS
                for word in decomposed[
                    1:
                ]:  # Skip full normalized name, check individual words
                    if word not in GENERIC_SINGLE_WORDS:
                        all_generic_single_words = False
                        break
            if not all_generic_single_words:
                break

        # If all tools are generic single words, return GENERAL with 0.0 confidence
        if all_generic_single_words and tool_names:
            return {
                "use_case": "GENERAL",
                "confidence": 0.0,
                "matched_keywords": [],
                "scores": scores,
            }

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
