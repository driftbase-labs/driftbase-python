#!/bin/bash
# Quick start script for LangGraph drift experiment
# Sonnet 4 (v1) vs Haiku 4.5 (v2)

set -e

echo "============================================================"
echo "  LangGraph Drift Experiment - Quick Start"
echo "============================================================"
echo ""

# Check API key
if [ -z "$ANTHROPIC_API_KEY" ]; then
    echo "❌ ERROR: ANTHROPIC_API_KEY not set"
    echo ""
    echo "Please set your API key:"
    echo "  export ANTHROPIC_API_KEY=\"your_key_here\""
    echo ""
    exit 1
fi

echo "✓ API key found"
echo ""

# Check dependencies
echo "Checking dependencies..."
python -c "from agent import build_agent; from scenarios import get_scenarios" 2>/dev/null
if [ $? -eq 0 ]; then
    echo "✓ Dependencies OK"
else
    echo "❌ Missing dependencies. Install with:"
    echo "  pip install driftbase langchain-core langgraph langchain-anthropic"
    exit 1
fi
echo ""

# Ask user for test type
echo "Choose test type:"
echo "  1) Quick test (3 scenarios, ~1 min total)"
echo "  2) Full experiment (100 scenarios × 2 repeats, ~30 min total)"
echo ""
read -p "Enter choice (1 or 2): " choice
echo ""

if [ "$choice" == "1" ]; then
    LIMIT="--limit 3 --repeat 1"
    EXPECTED_COUNT=3
    echo "Running QUICK TEST (3 scenarios per version)..."
elif [ "$choice" == "2" ]; then
    LIMIT=""
    EXPECTED_COUNT=200
    echo "Running FULL EXPERIMENT (200 runs per version)..."
else
    echo "Invalid choice. Exiting."
    exit 1
fi
echo ""

# Clean database
echo "Cleaning database..."
rm -f ~/.driftbase/runs.db
echo "✓ Database cleaned"
echo ""

# Run v1
echo "============================================================"
echo "  Running v1 (Sonnet 4)..."
echo "============================================================"
echo ""
python run_experiment.py --version v1 $LIMIT

# Check v1 results
v1_count=$(sqlite3 ~/.driftbase/runs.db "SELECT COUNT(*) FROM agent_runs_local WHERE deployment_version='v1'" 2>/dev/null || echo "0")
echo ""
if [ "$v1_count" == "$EXPECTED_COUNT" ]; then
    echo "✅ v1: $v1_count runs saved (expected $EXPECTED_COUNT)"
else
    echo "⚠️  v1: $v1_count runs saved (expected $EXPECTED_COUNT)"
    echo ""
    echo "To debug, run:"
    echo "  export DRIFTBASE_DEBUG=1"
    echo "  python run_experiment.py --version v1 --limit 1 --repeat 1"
    exit 1
fi
echo ""

# Run v2
echo "============================================================"
echo "  Running v2 (Haiku 4.5)..."
echo "============================================================"
echo ""
python run_experiment.py --version v2 $LIMIT

# Check v2 results
v2_count=$(sqlite3 ~/.driftbase/runs.db "SELECT COUNT(*) FROM agent_runs_local WHERE deployment_version='v2'" 2>/dev/null || echo "0")
echo ""
if [ "$v2_count" == "$EXPECTED_COUNT" ]; then
    echo "✅ v2: $v2_count runs saved (expected $EXPECTED_COUNT)"
else
    echo "⚠️  v2: $v2_count runs saved (expected $EXPECTED_COUNT)"
    echo ""
    echo "To debug, run:"
    echo "  export DRIFTBASE_DEBUG=1"
    echo "  python run_experiment.py --version v2 --limit 1 --repeat 1"
    exit 1
fi
echo ""

# Run analysis
echo "============================================================"
echo "  Generating Drift Report..."
echo "============================================================"
echo ""
python analyze.py

echo ""
echo "============================================================"
echo "  ✅ SUCCESS!"
echo "============================================================"
echo ""
echo "Results:"
echo "  - v1 (Sonnet 4): $v1_count runs"
echo "  - v2 (Haiku 4.5): $v2_count runs"
echo "  - Drift report generated above"
echo ""
echo "Database location:"
echo "  ~/.driftbase/runs.db"
echo ""
echo "To inspect database:"
echo "  sqlite3 ~/.driftbase/runs.db"
echo "  > SELECT deployment_version, tool_call_count, tool_sequence FROM agent_runs_local LIMIT 5;"
echo ""
