"""
Sentinel.AI — stress-test pipeline (no LLM needed)
Simulates a 3-step travel planning pipeline with configurable failure modes.

Contracts:
  research    accepts: {destination, budget, days}
  write       accepts: {hotels, flight_cost}
"""

import os
import sentinel

API_KEY = os.environ.get("SENTINEL_API_KEY", "")

def init(api_key: str):
    global API_KEY
    API_KEY = api_key
    sentinel.init(api_key=api_key)

    # Contract: what "research" step accepts from "plan"
    sentinel.register_contract(
        agent="research",
        accepts={
            "destination": {"type": "string",  "required": True,  "min_length": 1},
            "budget":      {"type": "number",   "required": True,  "min": 100},
            "days":        {"type": "number",   "required": True,  "min": 1, "max": 30},
        },
    )

    # Contract: what "write_itinerary" step accepts from "research"
    sentinel.register_contract(
        agent="write_itinerary",
        accepts={
            "hotels":      {"type": "array",  "required": True},
            "flight_cost": {"type": "number", "required": True, "min": 0},
        },
    )


# ── Simulated steps ───────────────────────────────────────────────────────────

DESTINATIONS = {
    "tokyo":  {"destination": "Tokyo",    "budget": 3000, "days": 5},
    "paris":  {"destination": "Paris",    "budget": 2500, "days": 7},
    "nyc":    {"destination": "New York", "budget": 1800, "days": 4},
    "london": {"destination": "London",   "budget": 2800, "days": 6},
    "bali":   {"destination": "Bali",     "budget": 1500, "days": 10},
}

HOTELS = {
    "Tokyo":    ["Shinjuku Granbell", "Park Hyatt Tokyo"],
    "Paris":    ["Hôtel Le Marais",   "Le Relais Montmartre"],
    "New York": ["Pod 51",            "The High Line Hotel"],
    "London":   ["The Hoxton",        "citizenM Tower of London"],
    "Bali":     ["COMO Uma Ubud",     "Alaya Resort Ubud"],
}


def _plan(query: str, failure_mode: str) -> dict:
    key = next((k for k in DESTINATIONS if k in query.lower()), "tokyo")
    result = DESTINATIONS[key].copy()

    if failure_mode == "budget_string":
        result["budget"] = "three thousand"   # violates type=number
    elif failure_mode == "missing_days":
        del result["days"]                     # violates required=True
    elif failure_mode == "negative_budget":
        result["budget"] = -500               # violates min=100

    return result


def _research(plan_result: dict, failure_mode: str) -> dict:
    dest = plan_result.get("destination", "Tokyo")
    result = {
        "hotels":      HOTELS.get(dest, ["Hotel A", "Hotel B"]),
        "flight_cost": round(plan_result.get("budget", 2000) * 0.3),
    }

    if failure_mode == "missing_hotels":
        del result["hotels"]   # violates required=True

    return result


def _write(research_result: dict, plan_result: dict) -> str:
    dest  = plan_result.get("destination", "?")
    days  = int(plan_result.get("days", 5))
    hotel = research_result.get("hotels", ["?"])[0]
    cost  = research_result.get("flight_cost", 0)
    lines = [f"{days}-day itinerary: {dest}", f"Stay: {hotel} · Flights ~${cost}"]
    for d in range(1, days + 1):
        lines.append(f"  Day {d}: Explore local neighbourhoods and cuisine.")
    return "\n".join(lines)


# ── Orchestrator ──────────────────────────────────────────────────────────────

def run_pipeline(query: str, failure_mode: str = "none") -> str:
    with sentinel.workflow("travel_planner") as run:

        with run.step("plan", step_type="llm_call") as step:
            trip_plan = _plan(query, failure_mode)
            step.set_input({"query": query})
            step.set_output(trip_plan)

        # handoff validates trip_plan against "research" contract
        sentinel.handoff(
            from_agent="plan",
            to_agent="research",
            payload=trip_plan,
            run_id=run.run_id,
        )

        with run.step("research", step_type="llm_call") as step:
            research_result = _research(trip_plan, failure_mode)
            step.set_input(trip_plan)
            step.set_output(research_result)

        # handoff validates research_result against "write_itinerary" contract
        sentinel.handoff(
            from_agent="research",
            to_agent="write_itinerary",
            payload=research_result,
            run_id=run.run_id,
        )

        with run.step("write_itinerary", step_type="tool_call") as step:
            itinerary = _write(research_result, trip_plan)
            step.set_input(research_result)
            step.set_output({"itinerary": itinerary})

    return itinerary
