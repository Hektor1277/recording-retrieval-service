from __future__ import annotations

import json
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from app.models.protocol import Credit, RetrievalItem, Seed


REQUESTED_FIELDS = [
    "links",
    "images",
    "performanceDateText",
    "venueText",
    "albumTitle",
    "label",
    "releaseDate",
    "notes",
]

GROUND_TRUTH_PLATFORMS = {"youtube", "bilibili"}
GROUP_ROLES = {"orchestra", "ensemble", "choir"}


@dataclass(slots=True)
class RoleInput:
    role: str
    display_name: str
    person_id: str = ""
    label: str = ""


@dataclass(slots=True)
class GeneratedScenario:
    variant: str
    recording_id: str
    item: RetrievalItem
    target_urls: list[str]
    evaluable: bool


def compact(value: object) -> str:
    return str(value or "").strip()


def workspace_root() -> Path:
    current = Path(__file__).resolve()
    for parent in current.parents:
        if (parent / "data" / "library" / "works.json").exists():
            return parent
    raise FileNotFoundError("unable to locate parent project data/library root")


def load_library_json(name: str, base_path: Path | None = None) -> list[dict]:
    root = base_path or workspace_root() / "data" / "library"
    return json.loads((root / name).read_text(encoding="utf-8"))


def load_library_indices(base_path: Path | None = None) -> tuple[dict[str, dict], dict[str, dict], dict[str, dict]]:
    root = base_path or workspace_root() / "data" / "library"
    recordings = {item["id"]: item for item in load_library_json("recordings.json", root)}
    works = {item["id"]: item for item in load_library_json("works.json", root)}
    composers = {item["id"]: item for item in load_library_json("composers.json", root)}
    return recordings, works, composers


def canonicalize_url(url: str) -> str:
    normalized = (url or "").strip()
    if not normalized:
        return ""
    parsed = urlparse(normalized)
    host = parsed.netloc.lower()
    path = parsed.path.rstrip("/")
    if "youtube.com" in host or "youtu.be" in host:
        if "youtu.be" in host and path:
            return f"youtube:{path.lstrip('/')}"
        video_id = parse_qs(parsed.query).get("v", [""])[0]
        if video_id:
            return f"youtube:{video_id}"
    if "bilibili.com" in host:
        parts = [part for part in path.split("/") if part]
        if len(parts) >= 2 and parts[0] == "video":
            return f"bilibili:{parts[1]}"
    return normalized.split("#", 1)[0].split("?", 1)[0]


def platform_from_canonical_url(value: str) -> str:
    normalized = compact(value)
    if normalized.startswith("youtube:"):
        return "youtube"
    if normalized.startswith("bilibili:"):
        return "bilibili"
    return ""


def find_work_id(*, works: dict[str, dict], work_id: str = "", title_latin: str = "", title: str = "") -> str:
    if work_id:
        if work_id not in works:
            raise KeyError(f"unknown work id: {work_id}")
        return work_id
    for candidate_id, work in works.items():
        if title_latin and work.get("titleLatin") == title_latin:
            return candidate_id
        if title and work.get("title") == title:
            return candidate_id
    raise KeyError("unable to resolve work id from provided selector")


def determine_work_type_hint(recording: dict) -> str:
    credits = recording.get("credits") or []
    roles = {str(credit.get("role") or "").strip() for credit in credits}
    has_soloist = "soloist" in roles
    has_group = any(role in GROUP_ROLES for role in roles)
    has_conductor = "conductor" in roles
    if has_soloist and (has_group or has_conductor):
        return "concerto"
    if has_group or has_conductor:
        return "orchestral"
    if has_soloist:
        return "chamber_solo"
    return "unknown"


def dedupe_credits(recording: dict) -> list[RoleInput]:
    seen: set[tuple[str, str, str]] = set()
    deduped: list[RoleInput] = []
    for credit in recording.get("credits") or []:
        role = str(credit.get("role") or "").strip()
        display_name = str(credit.get("displayName") or "").strip()
        person_id = str(credit.get("personId") or "").strip()
        if not role or not display_name:
            continue
        key = (role, person_id, display_name.casefold())
        if key in seen:
            continue
        seen.add(key)
        deduped.append(
            RoleInput(
                role=role,
                display_name=display_name,
                person_id=person_id,
                label=str(credit.get("label") or "").strip(),
            )
        )
    return deduped


def select_roles(recording: dict, work_type_hint: str) -> tuple[RoleInput | None, RoleInput | None, RoleInput | None]:
    credits = dedupe_credits(recording)
    groups = [credit for credit in credits if credit.role in GROUP_ROLES]
    conductors = [credit for credit in credits if credit.role == "conductor"]
    soloists = [credit for credit in credits if credit.role == "soloist"]

    def first_distinct(candidates: list[RoleInput], *, excluded_names: set[str]) -> RoleInput | None:
        for candidate in candidates:
            if candidate.display_name.casefold() not in excluded_names:
                return candidate
        return None

    if work_type_hint == "concerto":
        primary = first_distinct(soloists, excluded_names=set()) or first_distinct(conductors, excluded_names=set())
        excluded_names = {primary.display_name.casefold()} if primary else set()
        secondary = first_distinct(conductors, excluded_names=excluded_names)
        if secondary is None:
            secondary = first_distinct(soloists[1:], excluded_names=excluded_names)
        group = first_distinct(groups, excluded_names=excluded_names)
        return primary, secondary, group

    if work_type_hint == "orchestral":
        primary = first_distinct(conductors, excluded_names=set()) or first_distinct(groups, excluded_names=set())
        excluded_names = {primary.display_name.casefold()} if primary else set()
        group = first_distinct(groups, excluded_names=excluded_names)
        return primary, None, group

    if work_type_hint == "chamber_solo":
        primary = first_distinct(soloists, excluded_names=set())
        excluded_names = {primary.display_name.casefold()} if primary else set()
        secondary = first_distinct(soloists[1:], excluded_names=excluded_names)
        return primary, secondary, None

    primary = first_distinct(soloists + conductors + groups, excluded_names=set())
    return primary, None, None


def supported_target_urls(recording: dict) -> list[str]:
    targets: list[str] = []
    seen: set[str] = set()
    for link in recording.get("links") or []:
        url = str(link.get("url") or "").strip()
        platform = str(link.get("platform") or "").strip().lower()
        if not url or platform not in GROUND_TRUTH_PLATFORMS:
            continue
        canonical = canonicalize_url(url)
        if not canonical or canonical in seen:
            continue
        seen.add(canonical)
        targets.append(canonical)
    return targets


def build_source_line(
    *,
    composer: dict,
    work: dict,
    roles: list[RoleInput],
    performance_date_text: str,
) -> str:
    parts = [
        str(composer.get("name") or "").strip(),
        str(work.get("title") or "").strip(),
        *[role.display_name for role in roles],
        performance_date_text.strip() or "-",
    ]
    return " | ".join(part for part in parts if part)


def build_retrieval_item(
    *,
    recording: dict,
    work: dict,
    composer: dict,
    variant: str,
    work_type_hint: str,
    roles: list[RoleInput],
    performance_date_text: str,
) -> RetrievalItem:
    source_line = build_source_line(
        composer=composer,
        work=work,
        roles=roles,
        performance_date_text=performance_date_text,
    )
    return RetrievalItem(
        itemId=f"{recording['id']}-{variant}",
        recordingId=recording["id"],
        workId=recording["workId"],
        composerId=work["composerId"],
        workTypeHint=work_type_hint,
        sourceLine=source_line,
        seed=Seed(
            title=str(recording.get("title") or source_line),
            composerName=str(composer.get("name") or ""),
            composerNameLatin=str(composer.get("nameLatin") or ""),
            workTitle=str(work.get("title") or ""),
            workTitleLatin=str(work.get("titleLatin") or ""),
            catalogue=str(work.get("catalogue") or ""),
            performanceDateText=performance_date_text,
            venueText="",
            albumTitle="",
            label="",
            releaseDate="",
            credits=[
                Credit(
                    role=role.role,
                    personId=role.person_id,
                    displayName=role.display_name,
                    label=role.label,
                )
                for role in roles
            ],
            links=[],
            notes="",
        ),
        requestedFields=REQUESTED_FIELDS,
    )


def build_recording_scenarios(recording: dict, work: dict, composer: dict) -> list[GeneratedScenario]:
    work_type_hint = determine_work_type_hint(recording)
    primary, secondary, group = select_roles(recording, work_type_hint)
    full_roles = [role for role in [primary, secondary, group] if role is not None]
    partial_roles = [role for role in [primary] if role is not None]
    performance_date_text = str(recording.get("performanceDateText") or "").strip()
    targets = supported_target_urls(recording)

    scenarios = [
        GeneratedScenario(
            variant="full",
            recording_id=recording["id"],
            item=build_retrieval_item(
                recording=recording,
                work=work,
                composer=composer,
                variant="full",
                work_type_hint=work_type_hint,
                roles=full_roles,
                performance_date_text=performance_date_text,
            ),
            target_urls=targets,
            evaluable=bool(targets),
        ),
        GeneratedScenario(
            variant="partial",
            recording_id=recording["id"],
            item=build_retrieval_item(
                recording=recording,
                work=work,
                composer=composer,
                variant="partial",
                work_type_hint=work_type_hint,
                roles=partial_roles,
                performance_date_text="",
            ),
            target_urls=targets,
            evaluable=bool(targets),
        ),
    ]
    return scenarios


def build_work_dataset(
    *,
    work_id: str,
    recordings: dict[str, dict],
    works: dict[str, dict],
    composers: dict[str, dict],
) -> list[GeneratedScenario]:
    work = works[work_id]
    composer = composers[work["composerId"]]
    scenarios: list[GeneratedScenario] = []
    selected_recordings = [
        recording for recording in recordings.values() if recording.get("workId") == work_id
    ]
    selected_recordings.sort(key=lambda item: str(item.get("title") or item["id"]))
    for recording in selected_recordings:
        scenarios.extend(build_recording_scenarios(recording, work, composer))
    return scenarios


def scenario_to_dict(scenario: GeneratedScenario) -> dict[str, object]:
    return {
        "variant": scenario.variant,
        "recordingId": scenario.recording_id,
        "itemId": scenario.item.item_id,
        "workTypeHint": scenario.item.work_type_hint,
        "sourceLine": scenario.item.source_line,
        "evaluable": scenario.evaluable,
        "targetUrls": scenario.target_urls,
        "requestedFields": list(scenario.item.requested_fields),
        "seed": scenario.item.seed.model_dump(by_alias=True),
    }


def summarize_results(results: list[dict]) -> dict[str, dict[str, int]]:
    overall = {
        "total": 0,
        "evaluable": 0,
        "finalHit": 0,
        "candidateHit": 0,
        "relaxedFinalHit": 0,
        "relaxedCandidateHit": 0,
    }
    by_variant: dict[str, dict[str, int]] = defaultdict(
        lambda: {
            "total": 0,
            "evaluable": 0,
            "finalHit": 0,
            "candidateHit": 0,
            "relaxedFinalHit": 0,
            "relaxedCandidateHit": 0,
        }
    )
    strict_miss_reasons: dict[str, int] = defaultdict(int)
    for result in results:
        variant = str(result.get("variant") or "unknown")
        evaluable = bool(result.get("evaluable"))
        overall["total"] += 1
        by_variant[variant]["total"] += 1
        if not evaluable:
            continue
        overall["evaluable"] += 1
        by_variant[variant]["evaluable"] += 1
        if bool(result.get("finalHit")):
            overall["finalHit"] += 1
            by_variant[variant]["finalHit"] += 1
        if bool(result.get("candidateHit")):
            overall["candidateHit"] += 1
            by_variant[variant]["candidateHit"] += 1
        if bool(result.get("relaxedFinalHit")):
            overall["relaxedFinalHit"] += 1
            by_variant[variant]["relaxedFinalHit"] += 1
        if bool(result.get("relaxedCandidateHit")):
            overall["relaxedCandidateHit"] += 1
            by_variant[variant]["relaxedCandidateHit"] += 1
        miss_reason = compact(result.get("strictMissReason"))
        if miss_reason and miss_reason not in {"none", "not_evaluable"}:
            strict_miss_reasons[miss_reason] += 1
    return {
        "overall": overall,
        "byVariant": dict(by_variant),
        "strictMissReasons": dict(strict_miss_reasons),
    }


def classify_target_link_audit(*, available: bool, match_score: float | None) -> str:
    if not available:
        return "unavailable"
    if match_score is None:
        return "available_but_unscored"
    if match_score < 0.25:
        return "available_but_suspicious"
    return "available"


def summarize_link_audit(rows: list[dict]) -> dict[str, object]:
    by_status: dict[str, int] = defaultdict(int)
    by_platform: dict[str, dict[str, int]] = defaultdict(
        lambda: {"total": 0, "available": 0, "unavailable": 0}
    )
    available_count = 0
    unavailable_count = 0
    for row in rows:
        status = compact(row.get("auditStatus"))
        platform = compact(row.get("platform")) or "unknown"
        available = bool(row.get("available"))
        if status:
            by_status[status] += 1
        by_platform[platform]["total"] += 1
        if available:
            available_count += 1
            by_platform[platform]["available"] += 1
        else:
            unavailable_count += 1
            by_platform[platform]["unavailable"] += 1
    return {
        "total": len(rows),
        "available": available_count,
        "unavailable": unavailable_count,
        "byStatus": dict(by_status),
        "byPlatform": dict(by_platform),
    }


def classify_link_match(
    *,
    targets: list[str],
    links: list[dict[str, object]],
    alt_upload_confidence_threshold: float = 0.75,
) -> tuple[bool, str]:
    target_set = {compact(value) for value in targets if compact(value)}
    if not target_set:
        return False, "none"
    for link in links:
        canonical = compact(link.get("canonical"))
        if canonical and canonical in target_set:
            return True, "strict"
    target_platforms = {platform_from_canonical_url(value) for value in target_set if platform_from_canonical_url(value)}
    for link in links:
        canonical = compact(link.get("canonical"))
        platform = compact(link.get("platform")) or platform_from_canonical_url(canonical)
        confidence = float(link.get("confidence", 0.0) or 0.0)
        if platform and platform in target_platforms and confidence >= alt_upload_confidence_threshold:
            return True, "same_platform_alt_upload"
    return False, "none"


def evaluate_hit_metrics(
    *,
    targets: list[str],
    final_links: list[dict[str, object]],
    candidate_links: list[dict[str, object]],
) -> dict[str, object]:
    final_hit, final_match_type = classify_link_match(targets=targets, links=final_links)
    candidate_hit, candidate_match_type = classify_link_match(
        targets=targets,
        links=[*final_links, *candidate_links],
    )
    return {
        "finalHit": final_match_type == "strict",
        "candidateHit": candidate_match_type == "strict",
        "relaxedFinalHit": final_hit,
        "relaxedCandidateHit": candidate_hit,
        "finalMatchType": final_match_type,
        "candidateMatchType": candidate_match_type,
    }


def categorize_result_reason(result: dict[str, object]) -> str:
    if not bool(result.get("evaluable")):
        return "not_evaluable"
    if bool(result.get("finalHit")):
        return "none"
    if bool(result.get("relaxedFinalHit")):
        return "same_platform_alt_upload"
    if bool(result.get("candidateHit")):
        if any("LLM 归并超时" in compact(warning) for warning in result.get("warnings") or []):
            return "final_selection_after_llm_timeout"
        return "final_selection_miss"
    if bool(result.get("relaxedCandidateHit")):
        return "same_platform_alt_candidate_only"
    return "recall_miss"
