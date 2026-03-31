# Driftbase Drift Experiment

## Based on LangChain's Official Customer Support Bot Tutorial

This experiment replicates the architecture of [LangChain's Customer Support Bot tutorial](https://langchain-ai.github.io/langgraph/tutorials/customer-support/customer-support/)
— the most widely-used LangGraph example — and uses [Driftbase](https://github.com/driftbase-labs/driftbase-python) to detect
behavioral drift between two model versions.

**The question:** If you swap the model in a LangGraph agent and change nothing else,
does the agent's behavior change? By how much? Would anyone notice?

## Architecture

The tutorial's Part 1 agent (zero-shot, all 18 tools, no interrupts) is reproduced
with mock tool backends so the experiment is fully self-contained — no Tavily key,
no SQLite download, no external dependencies beyond Anthropic API.

All mock tools use **seeded randomness** based on input arguments, ensuring deterministic
output for identical inputs. This isolates model behavior changes from data variance.

```
agent.py              — LangGraph agent with 18 tools and seeded mock backends
scenarios.py          — 100 realistic queries with ground truth expected_tools
run_experiment.py     — Runs scenarios with correctness tracking and repeat support
analyze.py            — Generates drift report via driftbase diff
```

## Tools (matching the tutorial exactly)

| Category | Tools |
|---|---|
| Policy | `lookup_policy` |
| Flights | `fetch_user_flight_information`, `search_flights`, `update_ticket_to_new_flight`, `cancel_ticket` |
| Hotels | `search_hotels`, `book_hotel`, `update_hotel`, `cancel_hotel` |
| Car Rentals | `search_car_rentals`, `book_car_rental`, `update_car_rental`, `cancel_car_rental` |
| Excursions | `search_trip_recommendations`, `book_excursion`, `update_excursion`, `cancel_excursion` |
| Web Search | `tavily_search` (mock) |

## How to run

```bash
# Install dependencies
pip install driftbase langchain-core langgraph langchain-anthropic

# Set API key
export ANTHROPIC_API_KEY="your_key_here"

# Run v1 (claude-sonnet-4 baseline)
# Default: 100 scenarios × 2 repeats = 200 runs
python run_experiment.py --version v1

# Run v2 (claude-3.5-sonnet challenger)
python run_experiment.py --version v2

# Compare
python analyze.py

# Quick test (3 scenarios × 2 repeats)
python run_experiment.py --version v1 --limit 3
python run_experiment.py --version v2 --limit 3
driftbase diff v1 v2

# Adjust repeat count
python run_experiment.py --version v1 --repeat 3  # 100 × 3 = 300 runs
python run_experiment.py --version v1 --limit 10 --repeat 1  # 10 × 1 = 10 runs
```

### Verify the fix works

Run the unit test (no API key needed):
```bash
python test_tracer.py
```

This validates that the LangGraphTracer correctly:
- Links tool run_ids to the root graph
- Captures ALL tool calls (not just the setup node)
- Only saves once per graph invocation
- Cleans up all mappings

## What changes between v1 and v2

**Only the model.** Same system prompt, same tools, same scenarios, same tool
implementations. This isolates model-driven behavioral drift.

- **v1**: Claude Sonnet 4 (claude-sonnet-4-20250514)
- **v2**: Claude Haiku 4.5 (claude-haiku-4-5-20251001)

This comparison evaluates drift when switching from a flagship model to a faster,
more cost-effective model — a common production optimization.

## Experiment improvements

This upgraded experiment includes:

1. **Ground truth tracking**: Each scenario has `expected_tools` field for correctness measurement
2. **Seeded randomness**: All mock tools use deterministic output based on input arguments
3. **Repeat runs**: Default 2 repeats per scenario to measure intra-version consistency
4. **Same-tier comparison**: Sonnet 4 vs Sonnet 3.5 (not different model tiers)
5. **Statistical power**: 100 scenarios × 2 repeats = 200 runs per version
6. **Correctness metrics**: Track whether actual tools include all expected tools
7. **Consistency metrics**: Measure if same query → same tools across repeats

## Expected drift signals

- **Tool distribution shift** — different model may prefer different tools for the same query
- **Decision outcome changes** — different routing, different tool choices
- **Markov transition shifts** — different tool call ordering patterns
- **Correctness drift** — regression in meeting ground truth expectations
- **Consistency drift** — increased variance in tool selection for identical queries
- **Verbosity ratio** — response length changes between versions
- **Latency** — performance differences

## Credit

Agent architecture: [LangChain's Customer Support Bot Tutorial](https://langchain-ai.github.io/langgraph/tutorials/customer-support/customer-support/)
Drift detection: [Driftbase](https://github.com/driftbase-labs/driftbase-python)
