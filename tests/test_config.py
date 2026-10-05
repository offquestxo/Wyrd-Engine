from __future__ import annotations

import json

from apps.api import prompts
from apps.api.config import load_providers, load_sources, load_yaml
from apps.api.settings import PROMPTS_DIR


def test_every_task_route_points_at_a_defined_model() -> None:
    cfg = load_providers()
    expected = {
        "score_items",
        "parse_mention",
        "extract_from_document",
        "analyze_outliers",
        "second_opinion",
        "embed",
    }
    assert expected <= set(cfg.tasks)
    for task, steps in cfg.tasks.items():
        assert steps, task
        for step in steps:
            assert step.model in cfg.providers[step.provider].models, f"{task}: {step}"


def test_other_configs_load() -> None:
    assert load_sources().http.min_interval_s["api.gdeltproject.org"] >= 5
    assert {c["name"] for c in load_yaml("channels.yaml")["channels"]} >= {
        "Company Man",
        "Modern MBA",
        "Magnates Media",
    }
    assert len(load_yaml("scoring.yaml")["series"]) == 6


def test_router_prompts_render() -> None:
    schema = json.dumps({"type": "object"})
    for name in (
        "scout_scoring",
        "parse_mention",
        "doc_extraction",
        "outlier_analysis",
        "second_opinion",
    ):
        text = prompts.render(name, output_schema=schema)
        assert schema in text and "{{" not in text
    assert "{{" not in prompts.render("json_repair", output_schema=schema, error="bad")


def test_all_spec_prompt_files_exist() -> None:
    for name in (
        "orchestrator",
        "scout_scoring",
        "outlier_analysis",
        "researcher",
        "doc_extraction",
        "second_opinion",
    ):
        assert (PROMPTS_DIR / f"{name}.md").exists()


def test_every_route_has_a_currently_working_provider() -> None:
    """Groq has no key and Gemini keys are rejected (2026-10); every task must still have
    NVIDIA or Mistral to fall back on."""
    cfg = load_providers()
    for task, steps in cfg.tasks.items():
        providers = {s.provider for s in steps}
        assert providers & {"nvidia", "mistral"}, task
        if "gemini" in providers or "groq" in providers:
            assert "nvidia" in providers, task
