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

import asyncio, os, sys, functools, time
import sentinel
from sentinel import ContractViolationError

# ── Init ──────────────────────────────────────────────────────────────────────

SENTINEL_API_KEY = os.environ.get("SENTINEL_API_KEY") or (sys.argv[1] if len(sys.argv) > 1 else None)
OPENAI_API_KEY   = os.environ.get("OPENAI_API_KEY")

if not SENTINEL_API_KEY:
    print("Set SENTINEL_API_KEY env var or pass as first argument.")
    sys.exit(1)
if not OPENAI_API_KEY:
    print("Set OPENAI_API_KEY env var.")
    sys.exit(1)

sentinel.init(api_key=SENTINEL_API_KEY)

# ── MetaGPT config — set API key programmatically ─────────────────────────────
# Must happen before any metagpt imports that touch Config

os.makedirs(os.path.expanduser("~/.metagpt"), exist_ok=True)
with open(os.path.expanduser("~/.metagpt/config2.yaml"), "w") as f:
    f.write(f"""llm:
  api_type: "openai"
  model: "gpt-4o-mini"
  api_key: "{OPENAI_API_KEY}"
  max_token: 4096
""")

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

# ── Patch ActionNode._aask_v1 — the real LLM gateway in MetaGPT ───────────────
# Role._act() calls Action.run() → ActionNode._aask_v1() → BaseLLM.aask()
# Patching here gives us one trace per actual LLM call.

from metagpt.actions.action_node import ActionNode

_original_aask_v1 = ActionNode._aask_v1
_active_run_ref   = [None]
_role_outputs     = {}

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

@functools.wraps(_original_aask_v1)
async def _traced_aask_v1(self, prompt, schema, mode, images=None):
    run = _active_run_ref[0]
    if run is None:
        return await _original_aask_v1(self, prompt, schema, mode, images)

    # Derive a readable step name from the action class
    action_name = type(self).__name__ if hasattr(self, "__class__") else "llm_call"
    # Walk up: ActionNode lives inside an Action, which has a role
    role_name = "unknown"
    if hasattr(self, "llm") and hasattr(self.llm, "_role_name"):
        role_name = self.llm._role_name

    step_name = action_name
    t0 = time.time()

    with run.step(step_name, step_type="llm_call") as step:
        step.set_input({
            "action": action_name,
            "prompt_chars": len(str(prompt)) if prompt else 0,
        })
        result = await _original_aask_v1(self, prompt, schema, mode, images)
        duration_ms = int((time.time() - t0) * 1000)
        content = str(result) if result else ""
        step.set_output({
            "output_chars": len(content),
            "preview":      content[:200],
            "duration_ms":  duration_ms,
        })

    return result

ActionNode._aask_v1 = _traced_aask_v1

# ── Also patch Role._act to track which role is running + fire contracts ───────

from metagpt.roles.role import Role

_original_act = Role._act

@functools.wraps(_original_act)
async def _traced_act(self):
    role_name = self.__class__.__name__
    result = await _original_act(self)

    content = ""
    if result is not None:
        content = str(getattr(result, "content", result))

    if content:
        _role_outputs[role_name] = _role_outputs.get(role_name, "") + content

    return result

Role._act = _traced_act

# ── Wrap the full role run to fire handoff contracts once per role ─────────────

from metagpt.roles.role import Role as _Role

_original_run = _Role.run

@functools.wraps(_original_run)
async def _traced_role_run(self, with_message=None):
    role_name = self.__class__.__name__
    result = await _original_run(self, with_message)

    # Only fire handoff if the role produced output this turn
    content = _role_outputs.pop(role_name, "")
    run = _active_run_ref[0]

    if content and run and role_name in HANDOFF_CONTRACTS:
        from_agent, to_agent, make_payload = HANDOFF_CONTRACTS[role_name]
        payload = make_payload(content)
        sentinel.handoff(
            from_agent=from_agent,
            to_agent=to_agent,
            payload=payload,
            run_id=run.run_id,
        )

    return result

_Role.run = _traced_role_run

# ── Pipeline runner ───────────────────────────────────────────────────────────

async def run_software_team(idea: str):
    from metagpt.team import Team
    from metagpt.roles import ProductManager, Architect, Engineer, ProjectManager

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
            _role_outputs.clear()

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
            print(f"         ✓ done\n")
        except ContractViolationError as e:
            print(f"         ✗ BLOCKED — {e}\n")
        except Exception as e:
            print(f"         ! ERROR — {e}\n")

    print(f"  → https://www.agentsentinelai.com/dashboard\n")


if __name__ == "__main__":
    asyncio.run(main())
