"""
gpt-researcher + Sentinel.AI — deep instrumentation
====================================================
Patches gpt-researcher's internal LLM gateway so every LLM call
becomes a visible step in Sentinel — not just the two top-level phases.

Visible steps per run:
  • conduct_research  (phase wrapper)
      ↳ llm/gpt-4o-mini  (choose_agent)
      ↳ llm/gpt-4o-mini  (sub-query planning)
      ↳ llm/gpt-4o-mini  × N  (per-source summarisation)
  • [handoff validated: source_count ≥ 1]
  • write_report  (phase wrapper)
      ↳ llm/gpt-4o-mini  (report generation)
      ↳ llm/gpt-4o-mini  (introduction / conclusion / TOC)

Setup:
  pip install gpt-researcher sentinelai-sdk ddgs
  export OPENAI_API_KEY=sk-...
  export SENTINEL_API_KEY=sk_live_...
  RETRIEVER=duckduckgo python gpt_researcher_demo.py
"""

import asyncio, os, sys
import sentinel
from sentinel import ContractViolationError

# ── Init ──────────────────────────────────────────────────────────────────────

SENTINEL_API_KEY = os.environ.get("SENTINEL_API_KEY") or (sys.argv[1] if len(sys.argv) > 1 else None)
if not SENTINEL_API_KEY:
    print("Set SENTINEL_API_KEY env var or pass as first argument.")
    sys.exit(1)

sentinel.init(api_key=SENTINEL_API_KEY)

sentinel.register_contract(
    agent="write_report",
    accepts={
        "source_count": {"type": "number",  "required": True, "min": 1},
        "has_context":  {"type": "boolean", "required": True},
        "query":        {"type": "string",  "required": True, "min_length": 1},
    },
)

# ── Patch gpt-researcher's LLM gateway ───────────────────────────────────────
# Every internal LLM call routes through create_chat_completion().
# We wrap it so each call becomes a Sentinel step automatically.

# Patch at the OpenAI SDK class level — catches every AsyncOpenAI client
# created anywhere, including inside gpt-researcher's internals.
import openai.resources.chat.completions as _oai_completions
sentinel.patch_openai_async(_oai_completions.AsyncCompletions)


# ── Instrumented pipeline ─────────────────────────────────────────────────────

async def run_research(query: str) -> str:
    global _active_run_id
    from gpt_researcher import GPTResearcher

    researcher = GPTResearcher(query=query, report_type="research_report", verbose=False)

    with sentinel.workflow("gpt-researcher") as run:
        sentinel.set_active_run(run.run_id, "gpt-researcher")  # tell patch_openai_async which run we're in

        # Phase 1 — Research
        with run.step("conduct_research", step_type="tool_call") as step:
            step.set_input({"query": query})
            await researcher.conduct_research()
            sources = researcher.get_source_urls()
            context = researcher.get_research_context()
            step.set_output({
                "source_count":   len(sources),
                "context_chars":  len(str(context)),
                "sources":        sources[:5],
            })

        # Handoff — validate before writing
        sentinel.handoff(
            from_agent="conduct_research",
            to_agent="write_report",
            payload={
                "source_count": len(sources),
                "has_context":  bool(context),
                "query":        query,
            },
            run_id=run.run_id,
        )

        # Phase 2 — Write
        with run.step("write_report", step_type="llm_call") as step:
            step.set_input({"source_count": len(sources), "query": query})
            report = await researcher.write_report()
            step.set_output({"word_count": len(report.split()), "chars": len(report)})

    return report


# ── Runner ────────────────────────────────────────────────────────────────────

QUERIES = [
    "What is the impact of AI agents on software engineering in 2025?",
    "How do multi-agent systems handle failures in production?",
    "What are the best practices for LLM output validation?",
]

async def main():
    print(f"\n{'='*62}")
    print(f"  gpt-researcher + Sentinel.AI  (deep instrumentation)")
    print(f"  Dashboard: https://www.agentsentinelai.com/dashboard")
    print(f"{'='*62}\n")

    for i, query in enumerate(QUERIES, 1):
        print(f"[{i}/{len(QUERIES)}] {query[:58]}")
        try:
            report = await run_research(query)
            print(f"         ✓ {len(report.split())} words\n")
        except ContractViolationError as e:
            print(f"         ✗ BLOCKED — {e}\n")
        except Exception as e:
            print(f"         ! ERROR — {e}\n")

    print(f"  → https://www.agentsentinelai.com/dashboard\n")


if __name__ == "__main__":
    asyncio.run(main())
