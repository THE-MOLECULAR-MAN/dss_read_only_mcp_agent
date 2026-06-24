"""Tests for dss_mcp.tools.scoring.compute_demo_score and its sub-scorers."""

import pytest

from dss_mcp.tools.scoring import (
    _score_ai,
    _score_pedigree,
    _score_reliability,
    _score_visual,
    compute_demo_score,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _summary(**overrides) -> dict:
    """Minimal passing summary (clears all gates). Override any field as needed."""
    base = {
        "recipe_count": 3,
        "dataset_count": 3,
        "dashboard_count": 0,
        "total_tile_count": 0,
        "webapp_count": 0,
        "autostarter_webapp_count": 0,
        "recent_job_success_rate": None,
        "has_agents": False,
        "llm_connection_names": [],
        "recipe_counts_by_category": {"visual": 0, "code": 0, "prompt_llm": 0, "plugin": 0},
        "inferred_origin": "original",
        "contributor_count": 1,
    }
    base.update(overrides)
    return base


# ---------------------------------------------------------------------------
# Hard gates
# ---------------------------------------------------------------------------

class TestHardGates:
    def test_passes_with_exactly_3_recipes_and_3_datasets(self):
        result = compute_demo_score(_summary(recipe_count=3, dataset_count=3))
        assert result["gates_passed"] is True
        assert result["score"] >= 0

    def test_fails_when_recipe_count_below_3(self):
        result = compute_demo_score(_summary(recipe_count=2, dataset_count=5))
        assert result["gates_passed"] is False
        assert result["score"] == 0

    def test_fails_when_dataset_count_below_3(self):
        result = compute_demo_score(_summary(recipe_count=5, dataset_count=2))
        assert result["gates_passed"] is False
        assert result["score"] == 0

    def test_fails_when_both_below_threshold(self):
        result = compute_demo_score(_summary(recipe_count=1, dataset_count=1))
        assert result["gates_passed"] is False
        assert result["score"] == 0

    def test_gate_breakdown_present_when_passing(self):
        result = compute_demo_score(_summary())
        gates = result["breakdown"]["gates"]
        assert gates["recipe_count_gte_3"] is True
        assert gates["dataset_count_gte_3"] is True

    def test_gate_breakdown_present_when_failing(self):
        result = compute_demo_score(_summary(recipe_count=1))
        gates = result["breakdown"]["gates"]
        assert gates["recipe_count_gte_3"] is False

    def test_all_dimension_scores_zero_when_gates_fail(self):
        result = compute_demo_score(_summary(recipe_count=0, dataset_count=0))
        bd = result["breakdown"]
        assert bd["visual_story"] == 0
        assert bd["reliability"] == 0
        assert bd["ai_capability"] == 0
        assert bd["pedigree"] == 0

    def test_none_recipe_count_treated_as_zero(self):
        result = compute_demo_score(_summary(recipe_count=None, dataset_count=5))
        assert result["gates_passed"] is False
        assert result["score"] == 0

    def test_none_dataset_count_treated_as_zero(self):
        result = compute_demo_score(_summary(recipe_count=5, dataset_count=None))
        assert result["gates_passed"] is False
        assert result["score"] == 0

    def test_score_not_affected_by_recent_job_success_rate_value(self):
        # recent_job_success_rate is NOT a gate, only a soft score input
        result_none = compute_demo_score(_summary(recent_job_success_rate=None))
        result_low = compute_demo_score(_summary(recent_job_success_rate=0.1))
        # Both should pass gates; only the soft reliability score differs
        assert result_none["gates_passed"] is True
        assert result_low["gates_passed"] is True


# ---------------------------------------------------------------------------
# _score_visual — unit tests
# ---------------------------------------------------------------------------

class TestScoreVisual:
    def test_zero_when_no_dashboards_or_webapps(self):
        assert _score_visual(_summary()) == 0

    def test_dashboard_present_adds_15(self):
        assert _score_visual(_summary(dashboard_count=1, total_tile_count=0)) == 15

    def test_five_tiles_adds_extra_10(self):
        assert _score_visual(_summary(dashboard_count=1, total_tile_count=5)) == 25

    def test_four_tiles_no_extra(self):
        assert _score_visual(_summary(dashboard_count=1, total_tile_count=4)) == 15

    def test_webapp_adds_10(self):
        assert _score_visual(_summary(webapp_count=1)) == 10

    def test_autostarter_adds_5(self):
        assert _score_visual(_summary(webapp_count=1, autostarter_webapp_count=1)) == 15

    def test_autostarter_without_webapp_still_adds_5(self):
        # autostarter_webapp_count > 0 implies webapp exists; treat independently
        assert _score_visual(_summary(webapp_count=0, autostarter_webapp_count=1)) == 5

    def test_full_visual_score(self):
        s = _summary(dashboard_count=2, total_tile_count=10, webapp_count=1, autostarter_webapp_count=1)
        assert _score_visual(s) == 40

    def test_capped_at_40(self):
        # Construct an over-score scenario — all signals present twice
        s = _summary(dashboard_count=5, total_tile_count=20, webapp_count=3, autostarter_webapp_count=2)
        assert _score_visual(s) == 40

    def test_none_fields_treated_as_zero(self):
        s = _summary(dashboard_count=None, total_tile_count=None, webapp_count=None, autostarter_webapp_count=None)
        assert _score_visual(s) == 0


# ---------------------------------------------------------------------------
# _score_reliability — unit tests
# ---------------------------------------------------------------------------

class TestScoreReliability:
    def test_none_rate_returns_0(self):
        assert _score_reliability(_summary(recent_job_success_rate=None)) == 0

    def test_exactly_0_8_returns_30(self):
        assert _score_reliability(_summary(recent_job_success_rate=0.8)) == 30

    def test_above_0_8_returns_30(self):
        assert _score_reliability(_summary(recent_job_success_rate=1.0)) == 30

    def test_exactly_0_5_returns_15(self):
        assert _score_reliability(_summary(recent_job_success_rate=0.5)) == 15

    def test_between_0_5_and_0_8_returns_15(self):
        assert _score_reliability(_summary(recent_job_success_rate=0.7)) == 15

    def test_below_0_5_but_nonzero_returns_5(self):
        assert _score_reliability(_summary(recent_job_success_rate=0.3)) == 5

    def test_exactly_0_returns_5(self):
        # 0.0 is not None — project has run jobs but all failed
        assert _score_reliability(_summary(recent_job_success_rate=0.0)) == 5

    def test_just_below_0_8_returns_15(self):
        assert _score_reliability(_summary(recent_job_success_rate=0.799)) == 15


# ---------------------------------------------------------------------------
# _score_ai — unit tests
# ---------------------------------------------------------------------------

class TestScoreAI:
    def test_no_ai_signals_returns_0(self):
        assert _score_ai(_summary()) == 0

    def test_has_agents_adds_10(self):
        assert _score_ai(_summary(has_agents=True)) == 10

    def test_llm_connections_adds_5(self):
        assert _score_ai(_summary(llm_connection_names=["openai"])) == 5

    def test_prompt_llm_recipe_adds_5(self):
        s = _summary(recipe_counts_by_category={"visual": 0, "code": 0, "prompt_llm": 1, "plugin": 0})
        assert _score_ai(s) == 5

    def test_all_ai_signals_gives_20(self):
        s = _summary(
            has_agents=True,
            llm_connection_names=["openai"],
            recipe_counts_by_category={"visual": 0, "code": 0, "prompt_llm": 2, "plugin": 0},
        )
        assert _score_ai(s) == 20

    def test_capped_at_20(self):
        # Simulate future scenario where has_agents + connections + prompt_llm all very high
        s = _summary(
            has_agents=True,
            llm_connection_names=["a", "b", "c"],
            recipe_counts_by_category={"visual": 0, "code": 0, "prompt_llm": 5, "plugin": 0},
        )
        assert _score_ai(s) == 20

    def test_zero_prompt_llm_does_not_add_points(self):
        s = _summary(recipe_counts_by_category={"visual": 0, "code": 0, "prompt_llm": 0, "plugin": 0})
        assert _score_ai(s) == 0

    def test_empty_llm_connection_names_not_counted(self):
        assert _score_ai(_summary(llm_connection_names=[])) == 0

    def test_none_recipe_counts_by_category_handled(self):
        s = _summary(recipe_counts_by_category=None)
        assert _score_ai(s) == 0


# ---------------------------------------------------------------------------
# _score_pedigree — unit tests
# ---------------------------------------------------------------------------

class TestScorePedigree:
    def test_solutions_hub_gives_7(self):
        assert _score_pedigree(_summary(inferred_origin="solutions_hub")) == 7

    def test_tutorial_gives_3(self):
        assert _score_pedigree(_summary(inferred_origin="tutorial")) == 3

    def test_original_gives_2(self):
        assert _score_pedigree(_summary(inferred_origin="original")) == 2

    def test_imported_gives_1(self):
        assert _score_pedigree(_summary(inferred_origin="imported")) == 1

    def test_unknown_origin_gives_0(self):
        assert _score_pedigree(_summary(inferred_origin="unknown")) == 0

    def test_none_origin_gives_0(self):
        assert _score_pedigree(_summary(inferred_origin=None)) == 0

    def test_contributor_count_2_adds_3(self):
        assert _score_pedigree(_summary(inferred_origin="original", contributor_count=2)) == 5

    def test_contributor_count_above_2_adds_3(self):
        assert _score_pedigree(_summary(inferred_origin="original", contributor_count=10)) == 5

    def test_contributor_count_1_adds_0(self):
        assert _score_pedigree(_summary(inferred_origin="original", contributor_count=1)) == 2

    def test_solutions_hub_plus_2_contributors_capped_at_10(self):
        assert _score_pedigree(_summary(inferred_origin="solutions_hub", contributor_count=2)) == 10

    def test_none_contributor_count_treated_as_zero(self):
        assert _score_pedigree(_summary(inferred_origin="solutions_hub", contributor_count=None)) == 7


# ---------------------------------------------------------------------------
# compute_demo_score — integration / full score
# ---------------------------------------------------------------------------

class TestComputeDemoScore:
    def test_minimum_passing_project_scores_above_zero(self):
        result = compute_demo_score(_summary(inferred_origin="original"))
        assert result["score"] >= 2  # at minimum: original origin = 2

    def test_perfect_score(self):
        s = _summary(
            recipe_count=10,
            dataset_count=10,
            dashboard_count=2,
            total_tile_count=10,
            webapp_count=1,
            autostarter_webapp_count=1,
            recent_job_success_rate=1.0,
            has_agents=True,
            llm_connection_names=["openai"],
            recipe_counts_by_category={"visual": 0, "code": 0, "prompt_llm": 2, "plugin": 0},
            inferred_origin="solutions_hub",
            contributor_count=3,
        )
        result = compute_demo_score(s)
        assert result["score"] == 100
        assert result["gates_passed"] is True

    def test_breakdown_keys_always_present_when_passing(self):
        result = compute_demo_score(_summary())
        bd = result["breakdown"]
        assert "visual_story" in bd
        assert "reliability" in bd
        assert "ai_capability" in bd
        assert "pedigree" in bd
        assert "gates" in bd

    def test_breakdown_keys_always_present_when_failing(self):
        result = compute_demo_score(_summary(recipe_count=0))
        bd = result["breakdown"]
        assert "visual_story" in bd
        assert "reliability" in bd
        assert "ai_capability" in bd
        assert "pedigree" in bd
        assert "gates" in bd

    def test_score_is_sum_of_dimensions(self):
        s = _summary(
            dashboard_count=1,
            recent_job_success_rate=0.8,
            inferred_origin="tutorial",
        )
        result = compute_demo_score(s)
        bd = result["breakdown"]
        expected = bd["visual_story"] + bd["reliability"] + bd["ai_capability"] + bd["pedigree"]
        assert result["score"] == expected

    def test_score_bounded_0_to_100(self):
        result = compute_demo_score(_summary())
        assert 0 <= result["score"] <= 100

    def test_reliability_none_does_not_fail_gates(self):
        result = compute_demo_score(_summary(recent_job_success_rate=None))
        assert result["gates_passed"] is True

    def test_empty_summary_fails_gates(self):
        result = compute_demo_score({})
        assert result["gates_passed"] is False
        assert result["score"] == 0
