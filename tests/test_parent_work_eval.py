from __future__ import annotations

from app.services.parent_work_eval import build_recording_scenarios, summarize_results, workspace_root


def test_build_recording_scenarios_for_concerto_produces_full_and_partial_variants() -> None:
    recording = {
        "id": "recording-1",
        "workId": "work-1",
        "title": "Example Recording",
        "performanceDateText": "March 3, 1942 Berlin",
        "credits": [
            {"role": "orchestra", "displayName": "Berlin Philharmonic Orchestra", "personId": "person-orch"},
            {"role": "conductor", "displayName": "Wilhelm Furtwangler", "personId": "person-cond"},
            {"role": "soloist", "displayName": "Walter Gieseking", "personId": "person-solo"},
        ],
        "links": [
            {"platform": "youtube", "url": "https://www.youtube.com/watch?v=abc123xyz01"},
            {"platform": "bilibili", "url": "https://www.bilibili.com/video/BV1xx411c7mD"},
        ],
    }
    work = {
        "id": "work-1",
        "composerId": "composer-1",
        "title": "a小调钢琴协奏曲",
        "titleLatin": "Piano Concerto, Op.54",
        "catalogue": "Op.54",
    }
    composer = {"id": "composer-1", "name": "罗伯特·舒曼", "nameLatin": "Robert Schumann"}

    scenarios = build_recording_scenarios(recording, work, composer)

    assert [scenario.variant for scenario in scenarios] == ["full", "partial"]

    full_item = scenarios[0].item
    assert full_item.work_type_hint == "concerto"
    assert full_item.seed.performance_date_text == "March 3, 1942 Berlin"
    assert [credit.role for credit in full_item.seed.credits] == ["soloist", "conductor", "orchestra"]
    assert scenarios[0].target_urls == ["youtube:abc123xyz01", "bilibili:BV1xx411c7mD"]
    assert scenarios[0].evaluable is True

    partial_item = scenarios[1].item
    assert partial_item.seed.performance_date_text == ""
    assert [credit.role for credit in partial_item.seed.credits] == ["soloist"]
    assert partial_item.item_id == "recording-1-partial"


def test_summarize_results_groups_hits_by_variant_and_tracks_evaluable_cases() -> None:
    summary = summarize_results(
        [
            {"variant": "full", "evaluable": True, "finalHit": True, "candidateHit": True},
            {"variant": "full", "evaluable": True, "finalHit": False, "candidateHit": True},
            {"variant": "partial", "evaluable": True, "finalHit": False, "candidateHit": False},
            {"variant": "partial", "evaluable": False, "finalHit": False, "candidateHit": False},
        ]
    )

    assert summary["overall"] == {
        "total": 4,
        "evaluable": 3,
        "finalHit": 1,
        "candidateHit": 2,
    }
    assert summary["byVariant"]["full"] == {
        "total": 2,
        "evaluable": 2,
        "finalHit": 1,
        "candidateHit": 2,
    }
    assert summary["byVariant"]["partial"] == {
        "total": 2,
        "evaluable": 1,
        "finalHit": 0,
        "candidateHit": 0,
    }


def test_workspace_root_points_to_parent_project_root() -> None:
    assert (workspace_root() / "data" / "library" / "works.json").exists()
