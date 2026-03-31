# .claude Directory Structure

**Claude Code configuration and context for driftbase-python.**

## Current Structure

```
.claude/
├── CLAUDE.md                          # Main instructions (read first)
├── settings.local.json                # Claude Code settings
│
├── skills/                            # Task-specific deep dives
│   ├── scoring.md                     # Scoring pipeline (MOST CRITICAL)
│   ├── storage.md                     # SQLite backend patterns
│   ├── cli.md                         # CLI conventions
│   ├── testing.md                     # Test patterns
│   └── release.md                     # Release process
│
├── memory/                            # Critical facts Claude Code must remember
│   ├── hard_learned_lessons.md       # Bugs that cost hours (NEVER REPEAT)
│   ├── design_decisions.md           # Why things are the way they are
│   ├── known_issues.md               # Pre-existing bugs (don't fix without discussion)
│   └── api_surface.md                # Public API contract (breaking changes)
│
├── decisions/                         # Architecture Decision Records (ADRs)
│   ├── 001-scoring-pipeline-order.md
│   ├── 002-no-async-in-sdk.md
│   ├── 003-sqlite-only-free-tier.md
│   ├── 004-12-dimensions.md
│   └── 005-confidence-tiers.md
│
└── context/                           # Supporting documentation
    ├── glossary.md                    # Technical terms
    └── troubleshooting.md             # Common errors and fixes
```

## Usage

### Starting a New Session

1. **Read `CLAUDE.md` first** — Sets role, response style, never-do rules
2. **Check Skills section** — Points to relevant skill for your task
3. **Read relevant skill** — Deep dive on scoring, storage, CLI, testing, or release

### During Work

1. **memory/hard_learned_lessons.md** — Check before touching fragile areas (weights, migrations, releases)
2. **memory/design_decisions.md** — Understand why before changing architectural choices
3. **memory/known_issues.md** — Don't fix pre-existing bugs without discussion
4. **memory/api_surface.md** — Check before modifying public API

### After Hitting a Bug

**Add to memory/hard_learned_lessons.md** — Document:
- What went wrong
- Why it went wrong
- How to fix it
- How to prevent it

## Recommendations for Additional Files

### High Value (Create Next)

**context/production_patterns.md**
Real-world usage examples:
- Common @track decorator patterns
- Typical diff workflows
- Budget configuration examples
- Multi-agent comparison setups

**context/migration_guide.md**
Breaking changes across versions:
- 0.5.0 → 0.6.0: [tui] extra removed
- 0.6.0 → 0.7.0: watch/tail/push removed
- Future: dimension additions, schema changes

**decisions/006-weight-redistribution.md**
Why and how unavailable dimensions (semantic_drift, tool_sequence_transitions) get their weights redistributed proportionally.

**decisions/007-learned-weights-blending.md**
Why learned weights blend with calibrated (not replace), and how learned_factor scales with n.

### Medium Value

**context/performance_benchmarks.md**
Performance characteristics:
- Diff computation time vs run count (30 runs = 100ms, 500 runs = 2s)
- Bootstrap overhead (500 iterations adds 3-5s)
- Power analysis cost (negligible, <10ms)
- Database query performance

**memory/integration_quirks.md**
Framework-specific issues:
- LangGraph test failure (no dependency)
- LangChain tracer timing
- OpenAI streaming edge cases
- AutoGen multi-agent tracking

**decisions/008-jsd-vs-kl-divergence.md**
Why JSD instead of KL divergence for distribution comparisons (symmetry, boundedness).

**decisions/009-bootstrap-vs-parametric-ci.md**
Why bootstrap resampling instead of parametric CI (handles non-normal distributions).

### Lower Value (Nice to Have)

**context/use_case_reference.md**
Detailed breakdown of 14 use cases:
- Keyword tables per use case
- Weight presets rationale
- Effect sizes by use case
- Example agents for each category

**context/test_data_generation.md**
How to generate synthetic test data:
- make_runs() patterns
- Fingerprint generation
- Controlled variance for power analysis tests

**decisions/010-verdict-thresholds.md**
Why MONITOR/REVIEW/BLOCK thresholds are at current multipliers (2σ/3σ/4σ).

**decisions/011-tier1-floor-15.md**
Why TIER1 floor is 15 (not 10 or 20).

## Maintenance Rules

### When to Add to memory/

**hard_learned_lessons.md:**
- Any bug that took >2 hours to diagnose
- Any bug that shipped to production
- Any silent failure (feature broken but no error message)

**design_decisions.md:**
- When someone asks "why did we do it this way?"
- When a Claude Code session questions an architectural choice
- When a new developer needs context on a non-obvious design

**known_issues.md:**
- Any test marked `xfail`
- Any documented limitation
- Any "TODO: implement properly" in production code

**api_surface.md:**
- When adding new public function/class
- When considering removing/renaming public API
- Before any breaking change

### When to Add decisions/

Create new ADR when:
1. Making a significant architectural decision
2. Choosing between multiple valid approaches
3. Need to document rationale for future maintainers

**Template:**
```markdown
# ADR-NNN: Title

Status: Proposed | Accepted | Rejected | Superseded

Context: What is the problem we're solving?

Decision: What did we decide to do?

Rationale: Why did we choose this approach?

Consequences: What are the trade-offs?

Alternatives Considered: What else did we consider and why not?
```

### When to Add context/

Add supporting documentation when:
- New terminology introduced
- Common error pattern emerges
- Multiple people ask same question
- Production patterns become established

## Summary

**Most valuable files for future Claude Code sessions:**

1. **skills/scoring.md** — Prevents scoring pipeline bugs (weights, calibration, tiers)
2. **memory/hard_learned_lessons.md** — Prevents repeating expensive mistakes
3. **memory/design_decisions.md** — Explains non-obvious architectural choices
4. **memory/api_surface.md** — Prevents breaking changes
5. **context/troubleshooting.md** — Speeds up debugging

**Update these files proactively** as you work. Future sessions will thank you.
