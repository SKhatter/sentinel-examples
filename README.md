# sentinel-examples

Runnable demos for [sentinelai-sdk](https://pypi.org/project/sentinelai-sdk/) — tracing, contract enforcement, and failure replay for multi-agent AI workflows.

**Dashboard:** [www.agentsentinelai.com/dashboard](https://www.agentsentinelai.com/dashboard)

---

## Examples

| File | What it shows | LLM needed? |
|---|---|---|
| `stress_test.py` + `pipeline.py` | Contract enforcement across 15 runs (8 success + 7 blocked) | No |
| `gpt_researcher_demo.py` | Deep tracing of gpt-researcher — every internal LLM call as a step | Yes (OpenAI) |

---

## Setup

```bash
pip install sentinelai-sdk
```

Get a Sentinel API key: open the dashboard → ⚙️ Settings → Generate Key. Free, no credit card required.

---

## Example 1 — Stress test (no LLM needed)

Simulates a 3-step travel planning pipeline and fires 15 runs with a mix of valid and invalid inputs. No OpenAI key required — steps return mock data.

```
query
  └─ plan()              → {destination, budget, days}
       │  ← handoff validated here (contract)
       └─ research()     → {hotels, flight_cost}
            │  ← handoff validated here (contract)
            └─ write_itinerary()  → itinerary string
```

### Failure modes

| Mode | What breaks | Expected outcome |
|---|---|---|
| `none` | — | Success |
| `budget_string` | `budget: "three thousand"` (wrong type) | Blocked at plan→research |
| `missing_days` | `days` field omitted | Blocked at plan→research |
| `negative_budget` | `budget: -500` (below min) | Blocked at plan→research |
| `missing_hotels` | `hotels` field omitted | Blocked at research→write |

### Run

```bash
SENTINEL_API_KEY=sk_live_... python stress_test.py
```

### Results (15 runs)

```
[01/15] Trip to Tokyo for 5 days                    ✓ success
[02/15] Plan a Paris vacation                       ✓ success
[03/15] Weekend in New York City                    ✓ success
[04/15] London for 6 days, $2800 budget             ✓ success
[05/15] 10 days in Bali                             ✓ success
[06/15] Tokyo again — week-long trip                ✓ success
[07/15] Paris long weekend                          ✓ success
[08/15] Budget trip to NYC                          ✓ success
[09/15] Trip to Tokyo                               ✗ BLOCKED   budget: expected number, got string
[10/15] Paris vacation planning                     ✗ BLOCKED   budget: expected number, got string
[11/15] Bali escape                                 ✗ BLOCKED   days: required field missing
[12/15] London trip                                 ✗ BLOCKED   days: required field missing
[13/15] Cheap Tokyo trip                            ✗ BLOCKED   budget: 100 minimum not met
[14/15] Tokyo trip — research fail                  ✗ BLOCKED   hotels: required field missing
[15/15] Paris — research fail                       ✗ BLOCKED   hotels: required field missing

success=8  blocked=7  errors=0
```

All 15 runs — including blocked ones — appear in the dashboard with full step traces and incident details.

---

## Example 2 — gpt-researcher (deep tracing)

Instruments [gpt-researcher](https://github.com/assafelovic/gpt-researcher) so every internal LLM call becomes a visible step under a single workflow run. Uses `patch_openai_async` at the class level to catch all `AsyncOpenAI` clients created inside gpt-researcher.

### Steps per run

```
gpt-researcher (workflow)
  ├─ openai/gpt-4.1      ~1.2s    tokens=416   (choose_agent)
  ├─ conduct_research    ~16s                   (phase wrapper)
  ├─ openai/o4-mini      ~7.7s    tokens=1468  (report generation)
  ├─ write_report        ~25s                   (phase wrapper)
  └─ openai/gpt-4.1      ~0.7s    tokens=203   (TOC / intro / conclusion)
```

### Setup

```bash
pip install gpt-researcher sentinelai-sdk ddgs
```

### Run

```bash
RETRIEVER=duckduckgo \
OPENAI_API_KEY=sk-... \
SENTINEL_API_KEY=sk_live_... \
python gpt_researcher_demo.py
```

> `RETRIEVER=duckduckgo` uses DuckDuckGo for web search — no Tavily API key needed.

### Queries

```
[1/3] What is the impact of AI agents on software engineering in 2025?  ✓ 1644 words
[2/3] How do multi-agent systems handle failures in production?          ✓ 1466 words
[3/3] What are the best practices for LLM output validation?            ✓ 1568 words
```

### How it works

```python
import sentinel
import openai.resources.chat.completions as _oai_completions

sentinel.init(api_key="sk_live_...")

# Patch at the class level — catches every AsyncOpenAI instance
# created anywhere, including inside gpt-researcher's internals
sentinel.patch_openai_async(_oai_completions.AsyncCompletions)

with sentinel.workflow("gpt-researcher") as run:
    sentinel.set_active_run(run.run_id, "gpt-researcher")
    # ... all internal LLM calls now appear as nested steps
```

---

## Contracts

Both examples use Sentinel's contract system to validate handoffs between agents:

```python
sentinel.register_contract(
    agent="research",
    accepts={
        "destination": {"type": "string",  "required": True, "min_length": 1},
        "budget":      {"type": "number",  "required": True, "min": 100},
        "days":        {"type": "number",  "required": True, "min": 1, "max": 30},
    },
)

# Validated at handoff time — raises ContractViolationError if invalid
sentinel.handoff(
    from_agent="plan",
    to_agent="research",
    payload=trip_plan,
    run_id=run.run_id,
)
```

When a contract fails, Sentinel:
- Raises `ContractViolationError` (blocking the downstream agent)
- Marks the run as `blocked` in the dashboard
- Creates an incident with the full payload for debugging

---

## Links

- [sentinelai-sdk on PyPI](https://pypi.org/project/sentinelai-sdk/)
- [Dashboard](https://www.agentsentinelai.com/dashboard)
- [gpt-researcher](https://github.com/assafelovic/gpt-researcher)



<img width="1511" height="855" alt="Screenshot 2026-04-12 at 5 06 07 PM" src="https://github.com/user-attachments/assets/7bab5e87-3d38-4d06-ba30-4c03e2bb0b10" />

