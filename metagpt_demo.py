"""
MetaGPT + Sentinel.AI — software team deep tracing
====================================================
Wraps MetaGPT's role pipeline (ProductManager → Architect → Engineer)
so every role execution becomes a visible Sentinel step, with
contract validation at each handoff.

Visible steps per run:
  metagpt-software-team (workflow)
    ↳ ProductManager   (writes PRD)          llm_call
    ↳ [handoff validated: prd_length ≥ 200]
    ↳ Architect         (writes design)      llm_call
    ↳ [handoff validated: design_length ≥ 100]
    ↳ ProjectManager    (writes tasks)       llm_call
    ↳ Engineer          (writes code)        llm_call

Setup:
  pip install metagpt sentinelai-sdk
  export OPENAI_API_KEY=sk-...
  export SENTINEL_API_KEY=sk_live_...
  python metagpt_demo.py
"""

import asyncio, os, sys, functools
import sentinel
from sentinel import ContractViolationError

# ── Init ──────────────────────────────────────────────────────────────────────

SENTINEL_API_KEY = os.environ.get("SENTINEL_API_KEY") or (sys.argv[1] if len(sys.argv) > 1 else None)
if not SENTINEL_API_KEY:
    print("Set SENTINEL_API_KEY env var or pass as first argument.")
    sys.exit(1)

sentinel.init(api_key=SENTINEL_API_KEY)

# ── Contracts ─────────────────────────────────────────────────────────────────

sentinel.register_contract(
    agent="Architect",
    accepts={
        "prd_length":   {"type": "number",  "required": True, "min": 200},
        "prd_complete": {"type": "boolean", "required": True},
    },
)

sentinel.register_contract(
    agent="Engineer",
    accepts={
        "design_length":   {"type": "number",  "required": True, "min": 100},
        "design_complete": {"type": "boolean", "required": True},
    },
)

# ── Patch Role.run — each full role execution = one Sentinel step ──────────────
# Patching run() rather than _act() because _act() is called multiple times
# per role (once per action). run() wraps the complete role turn.

from metagpt.roles.role import Role

_original_run = Role.run
_active_run_ref = [None]
_role_outputs   = {}

HANDOFF_CONTRACTS = {
    "ProductManager": ("ProductManager", "Architect",
                       lambda content: {
                           "prd_length":   len(content),
                           "prd_complete": len(content) >= 200,
                       }),
    "Architect": ("Architect", "Engineer",
                  lambda content: {
                      "design_length":   len(content),
                      "design_complete": len(content) >= 100,
                  }),
}

@functools.wraps(_original_run)
async def _traced_run(self, with_message=None):
    role_name = self.__class__.__name__
    run = _active_run_ref[0]
    if run is None:
        return await _original_run(self, with_message)

    with run.step(role_name, step_type="llm_call") as step:
        step.set_input({
            "role":    role_name,
            "profile": getattr(self, "profile", role_name),
        })
        result = await _original_run(self, with_message)

        # Collect the role's full output from its memory
        content = ""
        if hasattr(self, "rc") and hasattr(self.rc, "memory"):
            msgs = self.rc.memory.storage
            # Find the last message this role authored
            for msg in reversed(msgs):
                sent_by = getattr(msg, "sent_from", None) or getattr(msg, "role", None)
                if sent_by == role_name or sent_by is None:
                    content = str(getattr(msg, "content", ""))
                    break

        if not content and result is not None:
            content = str(getattr(result, "content", result))

        step.set_output({
            "output_chars": len(content),
            "preview":      content[:300] if content else "",
        })
        _role_outputs[role_name] = content

    # Validate handoff contract after the role fully completes
    if role_name in HANDOFF_CONTRACTS and content:
        from_agent, to_agent, make_payload = HANDOFF_CONTRACTS[role_name]
        payload = make_payload(content)
        sentinel.handoff(
            from_agent=from_agent,
            to_agent=to_agent,
            payload=payload,
            run_id=run.run_id,
        )

    return result

Role.run = _traced_run

# ── Pipeline runner ───────────────────────────────────────────────────────────

async def run_software_team(idea: str):
    from metagpt.team import Team
    from metagpt.roles import ProductManager, Architect, Engineer, ProjectManager

    _role_outputs.clear()

    team = Team()
    team.hire([
        ProductManager(),
        Architect(),
        ProjectManager(),
        Engineer(n_borg=1),
    ])
    team.invest(investment=3.0)

    with sentinel.workflow("metagpt-software-team") as run:
        sentinel.set_active_run(run.run_id, "metagpt-software-team")
        _active_run_ref[0] = run
        try:
            await team.run(idea=idea, n_round=5)
        finally:
            _active_run_ref[0] = None

# ── Ideas ─────────────────────────────────────────────────────────────────────

IDEAS = [
    "Build a CLI todo app in Python with add, list, and delete commands",
    "Create a Python script that checks if a URL is reachable and logs the result",
]

async def main():
    print(f"\n{'='*62}")
    print(f"  MetaGPT + Sentinel.AI  (software team tracing)")
    print(f"  Dashboard: https://www.agentsentinelai.com/dashboard")
    print(f"{'='*62}\n")

    for i, idea in enumerate(IDEAS, 1):
        print(f"[{i}/{len(IDEAS)}] {idea[:58]}")
        try:
            await run_software_team(idea)
            roles = list(_role_outputs.keys())
            print(f"         ✓ roles: {', '.join(roles)}\n")
        except ContractViolationError as e:
            print(f"         ✗ BLOCKED — {e}\n")
        except Exception as e:
            print(f"         ! ERROR — {e}\n")

    print(f"  → https://www.agentsentinelai.com/dashboard\n")


if __name__ == "__main__":
    asyncio.run(main())
