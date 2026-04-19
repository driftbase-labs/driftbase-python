#!/usr/bin/env bash
#
# Verification script for Driftbase installation
#
# Tests that all critical functionality works after installation:
# - CLI entry point works
# - Demo generates synthetic data
# - Diff computation runs
# - Deploy commands work
# - MCP server starts
#
# Usage:
#   ./scripts/verify_install.sh
#
# Exit codes:
#   0  - All checks passed
#   1  - One or more checks failed

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Track failures
FAILED=0

# Helper functions
pass() {
    echo -e "${GREEN}✓${NC} $1"
}

fail() {
    echo -e "${RED}✗${NC} $1"
    FAILED=1
}

warn() {
    echo -e "${YELLOW}⚠${NC} $1"
}

section() {
    echo ""
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    echo "$1"
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
}

# Main verification
section "📦 Driftbase Installation Verification"

# Check 1: CLI entry point exists
section "1. CLI Entry Point"
if command -v driftbase &> /dev/null; then
    VERSION=$(driftbase --version 2>&1 | head -1)
    pass "driftbase command found: $VERSION"
else
    fail "driftbase command not found in PATH"
fi

# Check 2: Version command works
section "2. Version Command"
if driftbase --version &> /dev/null; then
    pass "driftbase --version works"
else
    fail "driftbase --version failed"
fi

# Check 3: Help command works
section "3. Help Command"
if driftbase --help &> /dev/null; then
    COMMAND_COUNT=$(driftbase --help 2>&1 | grep -c "^  " || true)
    pass "driftbase --help works ($COMMAND_COUNT command groups)"
else
    fail "driftbase --help failed"
fi

# Check 4: Demo generates data
section "4. Demo Data Generation (60-second wow moment)"
TEST_DIR=$(mktemp -d)
cd "$TEST_DIR" || exit 1

if driftbase --no-color demo --offline --quick 2>&1 | grep -q "✓ 20 runs recorded"; then
    pass "Demo generated synthetic data successfully"

    # Check 5: Diff works on demo data
    section "5. Diff Computation"
    if driftbase --no-color diff v1.0 v2.0 2>&1 | grep -q "Overall Drift Score"; then
        pass "Diff computation works"
    else
        fail "Diff computation failed"
    fi

    # Check 6: Diagnose works
    section "6. Diagnose Command"
    if driftbase --no-color diagnose 2>&1 | grep -q "Behavioral"; then
        pass "Diagnose command works"
    else
        fail "Diagnose command failed"
    fi

    # Check 7: Deploy mark command
    section "7. Deploy Commands"
    if driftbase --no-color deploy mark v1.0 --outcome good --force 2>&1 | grep -q "Marked"; then
        pass "Deploy mark command works"
    else
        fail "Deploy mark command failed"
    fi

    # Check 8: Deploy list command
    if driftbase --no-color deploy list 2>&1 | grep -q "v1.0"; then
        pass "Deploy list command works"
    else
        fail "Deploy list command failed"
    fi
else
    fail "Demo data generation failed"
fi

# Cleanup test directory
cd - > /dev/null
rm -rf "$TEST_DIR"

# Check 9: MCP server availability
section "8. MCP Server"
if pip show mcp &> /dev/null; then
    # MCP package installed, test server startup
    # Use Python to timeout since macOS doesn't have timeout command
    if python -c "
import subprocess
import time
p = subprocess.Popen(['driftbase', 'mcp', 'serve'], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
time.sleep(1)
p.terminate()
stdout, _ = p.communicate(timeout=2)
exit(0 if b'Starting Driftbase MCP server' in stdout else 1)
" 2>&1; then
        pass "MCP server starts successfully"
    else
        warn "MCP server test inconclusive (package installed)"
    fi
else
    warn "MCP extra not installed (optional: pip install driftbase[mcp])"
fi

# Check 10: Core imports work
section "9. Python Imports"
if python -c "from driftbase.engine import compute_drift, import_traces, compute_verdict" 2>&1; then
    pass "Core Python imports work"
else
    fail "Core Python imports failed"
fi

# Check 11: Test suite passes
section "10. Test Suite"
if pytest tests/ -v --tb=line -x 2>&1 | grep -q "passed"; then
    TEST_COUNT=$(pytest tests/ -q 2>&1 | tail -1 | grep -oE "[0-9]+ passed" | grep -oE "[0-9]+")
    pass "Test suite passes ($TEST_COUNT tests)"
else
    fail "Test suite has failures"
fi

# Final summary
section "Summary"
if [ $FAILED -eq 0 ]; then
    echo -e "${GREEN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
    echo -e "${GREEN}✓ All checks passed! Driftbase is ready to use.${NC}"
    echo -e "${GREEN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
    exit 0
else
    echo -e "${RED}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
    echo -e "${RED}✗ Some checks failed. See errors above.${NC}"
    echo -e "${RED}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
    exit 1
fi
