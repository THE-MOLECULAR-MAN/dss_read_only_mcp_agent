"""Demo-readiness scoring for DSS projects.

compute_demo_score() operates entirely on a get_project_summary() result dict —
no extra API calls required. It uses a two-phase approach:

  Phase 1 — Hard gates: if any gate fails the project scores 0 regardless of
  other signals. Gates represent minimum viability for a customer demo.

  Phase 2 — Soft score (0–100): four weighted dimensions assessed only on
  projects that pass the gates.

The score is keyword-agnostic — it measures project health and demo-readiness
rather than topic relevance. Use it to rank candidates returned by
search_projects() after calling get_project_summary() on each.
"""

from __future__ import annotations

# Score ceilings per dimension (must sum to 100)
_VISUAL_MAX = 40
_RELIABILITY_MAX = 30
_AI_MAX = 20
_PEDIGREE_MAX = 10


def compute_demo_score(summary: dict) -> dict:
    """Return a demo-readiness score and breakdown for a project summary dict.

    Hard gates (either failure → score = 0):
      - recipe_count >= 3
      - dataset_count >= 3

    Soft score dimensions (only evaluated when gates pass):
      - visual_story   0–40   dashboards, tiles, web apps, autostarters
      - reliability    0–30   recent job success rate
      - ai_capability  0–20   agents, LLM connections, prompt recipes
      - pedigree       0–10   origin quality, contributor count

    Returns:
      score            int 0–100
      gates_passed     bool
      breakdown        dict with per-dimension scores and gate results
    """
    recipe_count = summary.get("recipe_count") or 0
    dataset_count = summary.get("dataset_count") or 0

    gates = {
        "recipe_count_gte_3": int(recipe_count) >= 3,
        "dataset_count_gte_3": int(dataset_count) >= 3,
    }
    gates_passed = all(gates.values())

    breakdown: dict = {"gates": gates}

    if not gates_passed:
        breakdown.update({
            "visual_story": 0,
            "reliability": 0,
            "ai_capability": 0,
            "pedigree": 0,
        })
        return {"score": 0, "gates_passed": False, "breakdown": breakdown}

    visual = _score_visual(summary)
    reliability = _score_reliability(summary)
    ai = _score_ai(summary)
    pedigree = _score_pedigree(summary)

    breakdown.update({
        "visual_story": visual,
        "reliability": reliability,
        "ai_capability": ai,
        "pedigree": pedigree,
    })

    return {
        "score": visual + reliability + ai + pedigree,
        "gates_passed": True,
        "breakdown": breakdown,
    }


def _score_visual(summary: dict) -> int:
    """Visual story dimension: dashboards + web apps (0–40)."""
    score = 0

    # Dashboards: up to 25 pts
    dash = summary.get("dashboard_count") or 0
    tiles = summary.get("total_tile_count") or 0
    if dash >= 1:
        score += 15
    if tiles >= 5:
        score += 10

    # Web apps: up to 15 pts
    webapps = summary.get("webapp_count") or 0
    autostart = summary.get("autostarter_webapp_count") or 0
    if webapps >= 1:
        score += 10
    if autostart >= 1:
        score += 5

    return min(score, _VISUAL_MAX)


def _score_reliability(summary: dict) -> int:
    """Reliability dimension: recent job success rate (0–30)."""
    rate = summary.get("recent_job_success_rate")
    if rate is None:
        return 0
    rate = float(rate)
    if rate >= 0.8:
        return 30
    if rate >= 0.5:
        return 15
    return 5  # has run jobs but low success rate


def _score_ai(summary: dict) -> int:
    """AI capability dimension: agents, LLM connections, prompt recipes (0–20)."""
    score = 0
    if summary.get("has_agents"):
        score += 10
    if summary.get("llm_connection_names"):
        score += 5
    counts = summary.get("recipe_counts_by_category") or {}
    if int(counts.get("prompt_llm", 0)) >= 1:
        score += 5
    return min(score, _AI_MAX)


def _score_pedigree(summary: dict) -> int:
    """Pedigree dimension: origin quality + contributor breadth (0–10)."""
    score = 0
    origin = summary.get("inferred_origin") or ""
    if origin == "solutions_hub":
        score += 7
    elif origin == "tutorial":
        score += 3
    elif origin == "original":
        score += 2
    elif origin == "imported":
        score += 1

    contributors = summary.get("contributor_count") or 0
    if int(contributors) >= 2:
        score += 3

    return min(score, _PEDIGREE_MAX)
