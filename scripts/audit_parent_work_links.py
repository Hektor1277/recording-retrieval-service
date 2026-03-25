from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path
from urllib.parse import urlparse

import httpx

from app.services.http_sources import score_recording_match
from app.services.parent_work_eval import (
    build_recording_scenarios,
    canonicalize_url,
    classify_target_link_audit,
    find_work_id,
    load_library_indices,
    summarize_link_audit,
)
from app.services.pipeline import InputNormalizer


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("--work-id", default="")
    parser.add_argument("--title-latin", default="Piano Concerto, Op.54")
    parser.add_argument("--title", default="")
    parser.add_argument(
        "--output",
        default="output/parent_work_eval_schumann_op54_link_audit.json",
    )
    return parser


def extract_bilibili_bvid(url: str) -> str:
    parts = [part for part in urlparse(url).path.split("/") if part]
    if len(parts) >= 2 and parts[0] == "video":
        return parts[1]
    return ""


async def fetch_youtube_oembed(client: httpx.AsyncClient, url: str) -> dict[str, object]:
    response = await client.get(
        "https://www.youtube.com/oembed",
        params={"url": url, "format": "json"},
    )
    if response.status_code != 200:
        return {
            "available": False,
            "statusCode": response.status_code,
            "resolvedCanonical": "",
            "title": "",
            "description": "",
            "uploader": "",
            "message": response.text[:200],
        }
    payload = response.json()
    return {
        "available": True,
        "statusCode": response.status_code,
        "resolvedCanonical": canonicalize_url(url),
        "title": str(payload.get("title") or "").strip(),
        "description": "",
        "uploader": str(payload.get("author_name") or "").strip(),
        "message": "",
    }


async def fetch_bilibili_view(client: httpx.AsyncClient, url: str) -> dict[str, object]:
    bvid = extract_bilibili_bvid(url)
    response = await client.get(
        "https://api.bilibili.com/x/web-interface/view",
        params={"bvid": bvid},
        headers={
            "referer": "https://www.bilibili.com",
            "user-agent": "Mozilla/5.0",
        },
    )
    if response.status_code != 200:
        return {
            "available": False,
            "statusCode": response.status_code,
            "resolvedCanonical": "",
            "title": "",
            "description": "",
            "uploader": "",
            "message": response.text[:200],
        }
    payload = response.json()
    if int(payload.get("code") or 0) != 0:
        return {
            "available": False,
            "statusCode": response.status_code,
            "resolvedCanonical": "",
            "title": "",
            "description": "",
            "uploader": "",
            "message": str(payload.get("message") or payload.get("msg") or "").strip(),
        }
    data = payload.get("data") or {}
    owner = data.get("owner") if isinstance(data.get("owner"), dict) else {}
    resolved_bvid = str(data.get("bvid") or bvid).strip()
    return {
        "available": True,
        "statusCode": response.status_code,
        "resolvedCanonical": f"bilibili:{resolved_bvid}" if resolved_bvid else "",
        "title": str(data.get("title") or "").strip(),
        "description": str(data.get("desc") or "").strip(),
        "uploader": str(owner.get("name") or "").strip(),
        "message": "",
    }


async def audit_link(
    client: httpx.AsyncClient,
    *,
    platform: str,
    url: str,
    drafts: list[object],
) -> dict[str, object]:
    if platform == "youtube":
        metadata = await fetch_youtube_oembed(client, url)
    elif platform == "bilibili":
        metadata = await fetch_bilibili_view(client, url)
    else:
        return {
            "available": False,
            "statusCode": 0,
            "resolvedCanonical": "",
            "title": "",
            "description": "",
            "uploader": "",
            "message": "unsupported platform",
            "auditStatus": "unsupported_platform",
            "matchScore": None,
        }
    match_score: float | None = None
    variant_scores: list[float] = []
    if bool(metadata.get("available")):
        text = " ".join(
            part for part in [str(metadata.get("title") or ""), str(metadata.get("description") or "")] if part
        )
        variant_scores = [
            round(
                score_recording_match(text, url, draft, uploader=str(metadata.get("uploader") or "")),
                4,
            )
            for draft in drafts
        ]
        if variant_scores:
            match_score = max(variant_scores)
    return {
        **metadata,
        "matchScore": match_score,
        "variantScores": variant_scores,
        "auditStatus": classify_target_link_audit(
            available=bool(metadata.get("available")),
            match_score=match_score,
        ),
    }


async def main() -> None:
    parser = build_parser()
    args = parser.parse_args()

    recordings, works, composers = load_library_indices()
    work_id = find_work_id(
        works=works,
        work_id=args.work_id,
        title_latin=args.title_latin,
        title=args.title,
    )
    work = works[work_id]
    composer = composers[work["composerId"]]
    normalizer = InputNormalizer()
    rows: list[dict[str, object]] = []

    async with httpx.AsyncClient(
        timeout=20.0,
        follow_redirects=True,
        headers={"user-agent": "Mozilla/5.0"},
    ) as client:
        selected_recordings = [
            recording for recording in recordings.values() if recording.get("workId") == work_id
        ]
        selected_recordings.sort(key=lambda item: str(item.get("title") or item["id"]))
        for recording in selected_recordings:
            scenarios = build_recording_scenarios(recording, work, composer)
            drafts = [normalizer.normalize(scenario.item) for scenario in scenarios]
            primary_scenario = scenarios[0]
            for link in recording.get("links") or []:
                platform = str(link.get("platform") or "").strip().lower()
                if platform not in {"youtube", "bilibili"}:
                    continue
                audit = await audit_link(
                    client,
                    platform=platform,
                    url=str(link.get("url") or "").strip(),
                    drafts=drafts,
                )
                rows.append(
                    {
                        "recordingId": recording["id"],
                        "recordingTitle": str(recording.get("title") or "").strip(),
                        "sourceLine": primary_scenario.item.source_line,
                        "platform": platform,
                        "url": str(link.get("url") or "").strip(),
                        "canonical": canonicalize_url(str(link.get("url") or "").strip()),
                        **audit,
                    }
                )

    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "work": {
            "workId": work_id,
            "title": str(work.get("title") or ""),
            "titleLatin": str(work.get("titleLatin") or ""),
            "composerName": str(composer.get("name") or ""),
            "composerNameLatin": str(composer.get("nameLatin") or ""),
        },
        "summary": summarize_link_audit(rows),
        "results": rows,
    }
    output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(payload["summary"], ensure_ascii=False, indent=2))
    print(output_path.as_posix())


if __name__ == "__main__":
    asyncio.run(main())
