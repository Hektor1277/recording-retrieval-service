from __future__ import annotations

import argparse
import asyncio
import json
import time
from pathlib import Path

from app.services.parent_work_eval import (
    build_work_dataset,
    categorize_result_reason,
    canonicalize_url,
    evaluate_hit_metrics,
    find_work_id,
    load_library_indices,
    scenario_to_dict,
    summarize_results,
    workspace_root,
)
from app.services.retrieval import build_default_retriever


def build_access_report_payload(
    *,
    scenario_access: dict[str, list[dict]],
    host_summary: dict[str, dict],
) -> dict[str, object]:
    scenarios: dict[str, dict[str, object]] = {}
    event_count = 0
    for scenario_id, events in scenario_access.items():
        event_count += len(events)
        scenarios[scenario_id] = {
            "eventCount": len(events),
            "failedEvents": sum(1 for event in events if not event.get("ok", False)),
            "slowEvents": sum(1 for event in events if float(event.get("durationMs", 0.0) or 0.0) >= 3000),
            "hosts": sorted({str(event.get("host", "")).strip() for event in events if str(event.get("host", "")).strip()}),
            "events": events,
        }
    return {
        "scenarioCount": len(scenario_access),
        "eventCount": event_count,
        "scenarios": scenarios,
        "hosts": host_summary,
    }


async def run_scenario(retriever, scenario) -> dict[str, object]:
    try:
        deadline = time.monotonic() + 55
        result = await asyncio.wait_for(retriever.retrieve(scenario.item, deadline=deadline), timeout=70)
    except TimeoutError:
        return {
            "itemId": scenario.item.item_id,
            "recordingId": scenario.recording_id,
            "variant": scenario.variant,
            "workTypeHint": scenario.item.work_type_hint,
            "sourceLine": scenario.item.source_line,
            "evaluable": scenario.evaluable,
            "targets": scenario.target_urls,
            "status": "timeout",
            "confidence": 0.0,
            "finalLinks": [],
            "candidateLinks": [],
            "finalHit": False,
            "candidateHit": False,
            "relaxedFinalHit": False,
            "relaxedCandidateHit": False,
            "versionFinalHit": False,
            "versionCandidateHit": False,
            "finalMatchType": "none",
            "candidateMatchType": "none",
            "finalVersionMatchType": "none",
            "candidateVersionMatchType": "none",
            "strictMissReason": "timeout",
            "warnings": ["scenario timeout after internal 55s / external 70s"],
        }
    final_link_details = [
        {
            "canonical": canonicalize_url(link.url),
            "url": link.url,
            "title": link.title or "",
            "confidence": float(link.confidence or 0.0),
            "platform": link.platform or "",
        }
        for link in result.result.links
    ]
    candidate_link_details = [
        {
            "canonical": canonicalize_url(link.url),
            "url": link.url,
            "title": link.title or "",
            "confidence": float(link.confidence or 0.0),
            "platform": link.platform or "",
        }
        for link in result.link_candidates
    ]
    hit_metrics = evaluate_hit_metrics(
        targets=scenario.target_urls,
        final_links=final_link_details,
        candidate_links=candidate_link_details,
    )
    payload = {
        "itemId": scenario.item.item_id,
        "recordingId": scenario.recording_id,
        "variant": scenario.variant,
        "workTypeHint": scenario.item.work_type_hint,
        "sourceLine": scenario.item.source_line,
        "evaluable": scenario.evaluable,
        "targets": scenario.target_urls,
        "status": result.status,
        "confidence": result.confidence,
        "finalLinks": [item["canonical"] for item in final_link_details if item["canonical"]],
        "candidateLinks": [item["canonical"] for item in candidate_link_details if item["canonical"]],
        "finalLinkDetails": final_link_details,
        "candidateLinkDetails": candidate_link_details,
        "warnings": result.warnings,
    }
    payload.update(hit_metrics)
    payload["strictMissReason"] = categorize_result_reason(payload)
    return payload


async def main(args: argparse.Namespace) -> None:
    recordings, works, composers = load_library_indices()
    selected_work_id = find_work_id(
        works=works,
        work_id=args.work_id,
        title_latin=args.title_latin,
        title=args.title,
    )
    scenarios = build_work_dataset(
        work_id=selected_work_id,
        recordings=recordings,
        works=works,
        composers=composers,
    )
    if args.limit:
        scenarios = scenarios[: args.limit]

    work = works[selected_work_id]
    composer = composers[work["composerId"]]
    dataset_payload = {
        "work": {
            "workId": selected_work_id,
            "title": work.get("title", ""),
            "titleLatin": work.get("titleLatin", ""),
            "catalogue": work.get("catalogue", ""),
            "composerName": composer.get("name", ""),
            "composerNameLatin": composer.get("nameLatin", ""),
        },
        "recordingCount": len({scenario.recording_id for scenario in scenarios}),
        "scenarioCount": len(scenarios),
        "variants": sorted({scenario.variant for scenario in scenarios}),
        "samples": [scenario_to_dict(scenario) for scenario in scenarios],
    }
    dataset_output = Path(args.dataset_output)
    dataset_output.parent.mkdir(parents=True, exist_ok=True)
    dataset_output.write_text(json.dumps(dataset_payload, ensure_ascii=False, indent=2), encoding="utf-8")

    retriever = build_default_retriever()
    results: list[dict[str, object]] = []
    scenario_access: dict[str, list[dict]] = {}
    try:
        for scenario in scenarios:
            results.append(await run_scenario(retriever, scenario))
            scenario_access[scenario.item.item_id] = list(getattr(retriever, "consume_access_events", lambda: [])())
    finally:
        close_retriever = getattr(retriever, "aclose", None)
        if callable(close_retriever):
            await close_retriever()

    results_payload = {
        "work": dataset_payload["work"],
        "summary": summarize_results(results),
        "results": results,
    }
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(results_payload, ensure_ascii=False, indent=2), encoding="utf-8")

    access_report_path = Path(args.access_report)
    access_report_path.parent.mkdir(parents=True, exist_ok=True)
    access_report_path.write_text(
        json.dumps(
            build_access_report_payload(
                scenario_access=scenario_access,
                host_summary=dict(getattr(retriever, "get_access_summary", lambda: {})().get("hosts", {})),
            ),
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    print(json.dumps(results_payload["summary"], ensure_ascii=False, indent=2))
    print(str(dataset_output))
    print(str(output_path))
    print(str(access_report_path))


if __name__ == "__main__":
    default_stem = "parent_work_eval_schumann_op54"
    output_dir = Path(__file__).resolve().parents[1] / "output"
    parser = argparse.ArgumentParser()
    parser.add_argument("--work-id", default="")
    parser.add_argument("--title-latin", default="Piano Concerto, Op.54")
    parser.add_argument("--title", default="")
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--dataset-output", default=str(output_dir / f"{default_stem}_dataset.json"))
    parser.add_argument("--output", default=str(output_dir / f"{default_stem}_results.json"))
    parser.add_argument("--access-report", default=str(output_dir / f"{default_stem}_access.json"))
    parsed_args = parser.parse_args()
    asyncio.run(main(parsed_args))
