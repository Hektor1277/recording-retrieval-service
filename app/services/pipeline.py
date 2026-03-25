from __future__ import annotations

import asyncio
import re
import time
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any, Protocol

from app.models.protocol import (
    EvidenceItem,
    ImageCandidate,
    LinkCandidate,
    LogEntry,
    ResultItemResponse,
    ResultPayload,
    RetrievalItem,
)

LOW_CONFIDENCE_THRESHOLD = 0.45
FINAL_CONFIDENCE_THRESHOLD = 0.85
CORROBORATED_CONFIDENCE_THRESHOLD = 0.65
SAME_RECORDING_THRESHOLD = 0.75
FINAL_LINK_CONFIDENCE_THRESHOLD = 0.65
FINAL_IMAGE_CONFIDENCE_THRESHOLD = 0.65

FINALIZABLE_FIELDS = {
    "performanceDateText",
    "venueText",
    "albumTitle",
    "label",
    "releaseDate",
}

STAGE_WEIGHTS = {
    "existing-link": 0.8,
    "high-quality": 1.0,
    "streaming": 3.0,
    "fallback": 0.4,
    "llm": 0.5,
}


@dataclass(slots=True)
class RawInputEnvelope:
    item_id: str
    title: str
    source_line: str
    raw_text: str
    existing_links: list[dict[str, str]]


@dataclass(slots=True)
class DraftRecordingEntry:
    item_id: str
    title: str
    composer_name: str
    composer_name_latin: str
    work_title: str
    work_title_latin: str
    catalogue: str
    performance_date_text: str
    venue_text: str
    album_title: str
    label: str
    release_date: str
    notes: str
    source_line: str
    raw_text: str
    existing_links: list[dict[str, str]]
    primary_names: list[str] = field(default_factory=list)
    primary_names_latin: list[str] = field(default_factory=list)
    secondary_names: list[str] = field(default_factory=list)
    secondary_names_latin: list[str] = field(default_factory=list)
    query_lead_names: list[str] = field(default_factory=list)
    query_lead_names_latin: list[str] = field(default_factory=list)
    lead_names: list[str] = field(default_factory=list)
    lead_names_latin: list[str] = field(default_factory=list)
    ensemble_names: list[str] = field(default_factory=list)
    ensemble_names_latin: list[str] = field(default_factory=list)


@dataclass(slots=True)
class RetrievalProfile:
    category: str
    tags: list[str]
    queries: list[str]
    latin_queries: list[str] = field(default_factory=list)
    zh_queries: list[str] = field(default_factory=list)
    mixed_queries: list[str] = field(default_factory=list)


@dataclass(slots=True)
class SourceRecord:
    url: str
    source_label: str
    source_kind: str
    title: str
    description: str
    platform: str
    weight: float
    same_recording_score: float
    duration_seconds: int = 0
    uploader: str = ""
    view_count: int = 0
    fields: dict[str, str] = field(default_factory=dict)
    images: list[dict[str, Any]] = field(default_factory=list)


@dataclass(slots=True)
class FieldCandidate:
    field: str
    value: str
    confidence: float
    source_url: str
    source_label: str
    accepted: bool


class SourceProvider(Protocol):
    async def inspect_existing_links(
        self,
        draft: DraftRecordingEntry,
        profile: RetrievalProfile,
    ) -> list[dict[str, Any]]: ...

    async def search_high_quality(
        self,
        draft: DraftRecordingEntry,
        profile: RetrievalProfile,
    ) -> list[dict[str, Any]]: ...

    async def search_streaming(
        self,
        draft: DraftRecordingEntry,
        profile: RetrievalProfile,
    ) -> list[dict[str, Any]]: ...

    async def search_fallback(
        self,
        draft: DraftRecordingEntry,
        profile: RetrievalProfile,
    ) -> list[dict[str, Any]]: ...

    async def aclose(self) -> None: ...


class LlmClient(Protocol):
    async def synthesize(
        self,
        draft: DraftRecordingEntry,
        profile: RetrievalProfile,
        records: list[SourceRecord],
    ) -> dict[str, Any]: ...


def compact(value: Any) -> str:
    return str(value or "").strip()


def resolve_credit_bucket(*, work_type: str, role: str) -> str:
    role = compact(role).lower()
    work_type = compact(work_type).lower()
    if role in {"orchestra", "ensemble", "choir", "group"}:
        return "ensemble"
    if work_type == "concerto":
        if role == "soloist":
            return "primary"
        if role in {"conductor", "singer", "instrumentalist", "person"}:
            return "secondary"
    elif work_type == "opera_vocal":
        if role == "conductor":
            return "primary"
        if role in {"soloist", "singer", "instrumentalist", "person"}:
            return "secondary"
    elif work_type == "chamber_solo":
        if role in {"soloist", "instrumentalist", "person"}:
            return "primary"
        if role in {"conductor", "singer"}:
            return "secondary"
    else:
        if role == "conductor":
            return "primary"
        if role in {"soloist", "singer", "instrumentalist", "person"}:
            return "secondary"
    return "ignore"


def build_query_lead_terms(
    primary_values: list[str],
    secondary_values: list[str],
    *,
    prefer_collaboration: bool = False,
) -> list[str]:
    if primary_values and secondary_values:
        combined = [
            " ".join([primary_values[0], secondary_values[0]]).strip(),
            " / ".join([primary_values[0], secondary_values[0]]).strip(),
        ]
        if prefer_collaboration:
            return dedupe_preserve_order([*combined, *primary_values, *secondary_values])
        return dedupe_preserve_order([*primary_values, combined[0], *secondary_values, combined[1]])
    return dedupe_preserve_order([*primary_values, *secondary_values])


class InputNormalizer:
    def normalize(self, item: RetrievalItem) -> DraftRecordingEntry:
        primary_names: list[str] = []
        primary_names_latin: list[str] = []
        secondary_names: list[str] = []
        secondary_names_latin: list[str] = []
        ensembles: list[str] = []
        ensembles_latin: list[str] = []
        title_people, title_groups, title_date_hint = infer_title_entities(item.seed.title)
        work_type = compact(item.work_type_hint).lower()
        for credit in item.seed.credits:
            display_name = strip_alias_annotations(compact(credit.display_name))
            label = compact(credit.label)
            primary_label = compact(display_name or label)
            role = compact(credit.role).lower()
            explicit_latin = extract_explicit_latin_alias(credit.display_name) or extract_explicit_latin_alias(credit.label)
            if not primary_label:
                continue
            latin_value = ""
            if explicit_latin:
                latin_value = explicit_latin
            elif label and looks_latin(label):
                latin_value = label
            elif looks_latin(primary_label):
                latin_value = primary_label

            bucket = resolve_credit_bucket(work_type=work_type, role=role)
            if work_type == "chamber_solo" and role in {"soloist", "instrumentalist", "person"} and primary_names:
                bucket = "secondary"
            if work_type == "concerto" and role == "soloist" and primary_names:
                bucket = "secondary"
            if bucket == "primary":
                primary_names.append(primary_label)
                if latin_value:
                    primary_names_latin.append(latin_value)
            elif bucket == "secondary":
                secondary_names.append(primary_label)
                if latin_value:
                    secondary_names_latin.append(latin_value)
            elif bucket == "lead":
                primary_names.append(primary_label)
                if latin_value:
                    primary_names_latin.append(latin_value)
            if role in {"orchestra", "ensemble", "choir", "group"}:
                ensembles.append(primary_label)
                if explicit_latin:
                    ensembles_latin.append(explicit_latin)
                elif label and looks_latin(label):
                    ensembles_latin.append(label)
                elif looks_latin(primary_label):
                    ensembles_latin.append(primary_label)

        if primary_names and not secondary_names and work_type in {"concerto", "chamber_solo", "opera_vocal"}:
            for inferred_name in title_people:
                if any(person_variant_matches(inferred_name, existing) for existing in [*primary_names, *secondary_names]):
                    continue
                secondary_names.append(inferred_name)
                if looks_latin(inferred_name):
                    secondary_names_latin.append(inferred_name)
        if not ensembles:
            for inferred_group in title_groups:
                if inferred_group in ensembles:
                    continue
                ensembles.append(inferred_group)
                if looks_latin(inferred_group):
                    ensembles_latin.append(inferred_group)

        title_performance_context = extract_title_performance_context(item.seed.title)
        performance_date_text = compact(item.seed.performance_date_text)
        if not performance_date_text:
            if work_type == "chamber_solo" and title_performance_context:
                performance_date_text = title_performance_context
            else:
                performance_date_text = title_date_hint

        leads = dedupe_preserve_order([*primary_names, *secondary_names])
        leads_latin = dedupe_preserve_order([*primary_names_latin, *secondary_names_latin])
        if not leads or not ensembles:
            inferred_leads, inferred_groups = infer_people_from_source_line(item.source_line)
            if not leads:
                leads = inferred_leads
                leads_latin = [value for value in inferred_leads if looks_latin(value)]
            if not ensembles:
                ensembles = inferred_groups
                ensembles_latin = [value for value in inferred_groups if looks_latin(value)]

        raw_text = " | ".join(
            value
            for value in [
                item.source_line,
                item.seed.title,
                item.seed.composer_name,
                item.seed.work_title,
                performance_date_text,
            ]
            if compact(value)
        )
        envelope = RawInputEnvelope(
            item_id=item.item_id,
            title=item.seed.title,
            source_line=item.source_line,
            raw_text=raw_text,
            existing_links=[
                {"platform": compact(link.platform), "url": compact(link.url), "title": compact(link.title)}
                for link in item.seed.links
                if compact(link.url)
            ],
        )
        prefer_collaboration = work_type in {"concerto", "chamber_solo", "opera_vocal"}
        query_lead_names = build_query_lead_terms(
            primary_names,
            secondary_names,
            prefer_collaboration=prefer_collaboration,
        )
        query_lead_names_latin = build_query_lead_terms(
            primary_names_latin,
            secondary_names_latin,
            prefer_collaboration=prefer_collaboration,
        )
        if not query_lead_names:
            query_lead_names = leads
        if not query_lead_names_latin:
            query_lead_names_latin = leads_latin

        return DraftRecordingEntry(
            item_id=envelope.item_id,
            title=compact(item.seed.title),
            composer_name=compact(item.seed.composer_name),
            composer_name_latin=compact(item.seed.composer_name_latin),
            work_title=compact(item.seed.work_title),
            work_title_latin=compact(item.seed.work_title_latin),
            catalogue=compact(item.seed.catalogue),
            performance_date_text=performance_date_text,
            venue_text=compact(item.seed.venue_text),
            album_title=compact(item.seed.album_title),
            label=compact(item.seed.label),
            release_date=compact(item.seed.release_date),
            notes=compact(item.seed.notes),
            source_line=envelope.source_line,
            raw_text=envelope.raw_text,
            existing_links=envelope.existing_links,
            primary_names=dedupe_preserve_order(primary_names),
            primary_names_latin=dedupe_preserve_order(primary_names_latin),
            secondary_names=dedupe_preserve_order(secondary_names),
            secondary_names_latin=dedupe_preserve_order(secondary_names_latin),
            query_lead_names=dedupe_preserve_order(query_lead_names),
            query_lead_names_latin=dedupe_preserve_order(query_lead_names_latin),
            lead_names=dedupe_preserve_order(leads),
            lead_names_latin=dedupe_preserve_order(leads_latin),
            ensemble_names=dedupe_preserve_order(ensembles),
            ensemble_names_latin=dedupe_preserve_order(ensembles_latin),
        )


class ProfileResolver:
    KEYWORD_MAP = {
        "piano": ("piano", "pianist", "钢琴"),
        "violin": ("violin", "violinist", "小提琴"),
        "vocal": ("soprano", "tenor", "baritone", "mezzo", "歌剧", "声乐", "女高音", "男高音"),
        "choral": ("choir", "chorus", "合唱"),
        "live": (" live ", "live in", "recorded live", "现场"),
        "studio": ("studio", "录音室"),
    }

    def __init__(self) -> None:
        self._normalizer = InputNormalizer()

    def resolve(self, item: RetrievalItem) -> RetrievalProfile:
        draft = self._normalizer.normalize(item)
        haystack = " ".join(
            [
                draft.title,
                draft.work_title,
                draft.work_title_latin,
                draft.source_line,
                " ".join(draft.lead_names),
                " ".join(draft.ensemble_names),
            ]
        ).lower()
        tags: list[str] = []
        padded = f" {haystack} "
        for tag, needles in self.KEYWORD_MAP.items():
            if any(needle.lower() in padded for needle in needles):
                tags.append(tag)

        latin_queries = build_queries(
            work_query=build_work_query(draft, prefer_latin=True),
            composer_query=compact(draft.composer_name_latin),
            lead_terms=draft.query_lead_names_latin or [value for value in draft.query_lead_names if looks_latin(value)],
            ensemble_terms=draft.ensemble_names_latin or [value for value in draft.ensemble_names if looks_latin(value)],
            title=draft.title,
            performance_date_text=draft.performance_date_text,
        )
        zh_queries = build_queries(
            work_query=build_work_query(draft, prefer_latin=False),
            composer_query=compact(draft.composer_name),
            lead_terms=[value for value in draft.query_lead_names if contains_cjk(value)],
            ensemble_terms=[value for value in draft.ensemble_names if contains_cjk(value)],
            title=draft.title,
            performance_date_text=draft.performance_date_text,
        )
        mixed_queries = build_queries(
            work_query=build_work_query(draft, prefer_latin=False) or build_work_query(draft, prefer_latin=True),
            composer_query=compact(draft.composer_name_latin or draft.composer_name),
            lead_terms=dedupe_preserve_order([*draft.query_lead_names_latin, *draft.query_lead_names]),
            ensemble_terms=dedupe_preserve_order([*draft.ensemble_names_latin, *draft.ensemble_names]),
            title=draft.title,
            performance_date_text=draft.performance_date_text,
        )
        queries = latin_queries or mixed_queries or zh_queries

        return RetrievalProfile(
            category=item.work_type_hint,
            tags=tags,
            queries=queries,
            latin_queries=latin_queries,
            zh_queries=zh_queries,
            mixed_queries=mixed_queries,
        )


def build_work_query(draft: DraftRecordingEntry, *, prefer_latin: bool) -> str:
    work = compact(draft.work_title_latin if prefer_latin else draft.work_title)
    if not work:
        if prefer_latin:
            work = compact(build_latin_work_alias(draft.work_title))
        if not work:
            work = compact(draft.work_title if prefer_latin else draft.work_title_latin)
    catalogue = compact(draft.catalogue)
    if work and catalogue and catalogue.lower() not in work.lower():
        return f"{work} {catalogue}"
    return work or draft.title


def build_queries(
    *,
    work_query: str,
    composer_query: str,
    lead_terms: list[str],
    ensemble_terms: list[str],
    title: str,
    performance_date_text: str,
) -> list[str]:
    queries: list[str] = []
    lead = dedupe_preserve_order(lead_terms)[:3] or [""]
    ensemble = dedupe_preserve_order(ensemble_terms)[:3] or [""]
    shapes = [
        lambda lead_term, ensemble_term: [work_query, lead_term, ensemble_term, performance_date_text],
        lambda lead_term, ensemble_term: [composer_query, work_query, lead_term, ensemble_term, performance_date_text],
        lambda lead_term, ensemble_term: [composer_query, work_query, lead_term, ensemble_term],
        lambda lead_term, ensemble_term: [work_query, lead_term, performance_date_text],
        lambda lead_term, ensemble_term: [lead_term, ensemble_term, performance_date_text],
        lambda lead_term, ensemble_term: [work_query, ensemble_term, performance_date_text],
        lambda lead_term, ensemble_term: [lead_term, performance_date_text],
        lambda lead_term, ensemble_term: [lead_term, ensemble_term],
        lambda lead_term, ensemble_term: [title, lead_term, ensemble_term],
        lambda lead_term, ensemble_term: [ensemble_term, performance_date_text],
    ]
    for shape in shapes:
        for lead_term in lead:
            for ensemble_term in ensemble:
                parts = shape(lead_term, ensemble_term)
                query = " ".join(compact(part) for part in parts if compact(part))
                if query and query not in queries:
                    queries.append(query)
    return queries


def looks_latin(value: str) -> bool:
    normalized = compact(value)
    return bool(normalized) and bool(re.search(r"[A-Za-z]", normalized)) and not contains_cjk(normalized)


def contains_cjk(value: str) -> bool:
    return bool(re.search(r"[\u4e00-\u9fff]", value or ""))


def build_latin_work_alias(value: str) -> str:
    text = compact(value)
    if not text:
        return ""
    patterns = [
        (r"第([\u4e00-\u9fff\d两零十百]+)(?:号)?交响曲", "Symphony"),
        (r"第([\u4e00-\u9fff\d两零十百]+)(?:号)?协奏曲", "Concerto"),
        (r"第([\u4e00-\u9fff\d两零十百]+)(?:号)?奏鸣曲", "Sonata"),
    ]
    for pattern, kind in patterns:
        match = re.search(pattern, text)
        if not match:
            continue
        number = normalize_cn_number(match.group(1))
        if number:
            return f"{kind} No. {number}"
    return ""


def normalize_cn_number(value: str) -> str:
    normalized = compact(value)
    if normalized.isdigit():
        return normalized
    digits = {
        "零": 0,
        "一": 1,
        "二": 2,
        "两": 2,
        "三": 3,
        "四": 4,
        "五": 5,
        "六": 6,
        "七": 7,
        "八": 8,
        "九": 9,
    }
    units = {"十": 10, "百": 100}
    total = 0
    current = 0
    for char in normalized:
        if char in digits:
            current = digits[char]
        elif char in units:
            total += (current or 1) * units[char]
            current = 0
    return str(total + current) if total or current else ""


def strip_alias_annotations(value: str) -> str:
    text = compact(value)
    if not text:
        return ""
    text = re.sub(r"\(\s*EN\s*[:：].*?\)", "", text, flags=re.I)
    text = re.sub(r"[,，]\s*EN\s*[:：].*$", "", text, flags=re.I)
    return compact(text)


def extract_explicit_latin_alias(value: str) -> str:
    text = compact(value)
    if not text:
        return ""
    patterns = [
        r"EN\s*[:：]\s*([^()]+?)(?=\s*(?:CHN|CN|中文)\s*[:：]|$)",
        r"\(\s*EN\s*[:：]\s*([^()]+?)(?=\s*(?:CHN|CN|中文)\s*[:：]|\))",
    ]
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.I)
        if not match:
            continue
        alias = compact(match.group(1)).strip(" ,;|)")
        if alias and looks_latin(alias):
            return alias
    return ""


def normalize_source_record(payload: dict[str, Any]) -> SourceRecord:
    raw_weight = float(payload.get("weight", 0.0) or 0.0)
    weight = raw_weight / 100 if raw_weight > 1 else raw_weight
    return SourceRecord(
        url=compact(payload.get("url")),
        source_label=compact(payload.get("source_label") or payload.get("sourceLabel")),
        source_kind=compact(payload.get("source_kind") or payload.get("sourceKind")),
        title=compact(payload.get("title")),
        description=compact(payload.get("description")),
        platform=compact(payload.get("platform")) or "other",
        weight=max(0.0, min(1.0, weight if weight else 0.5)),
        same_recording_score=max(
            0.0,
            min(1.0, float(payload.get("same_recording_score", payload.get("sameRecordingScore", 0.0)) or 0.0)),
        ),
        duration_seconds=max(0, int(payload.get("duration_seconds", payload.get("durationSeconds", 0)) or 0)),
        uploader=compact(payload.get("uploader")),
        view_count=max(0, int(payload.get("view_count", payload.get("viewCount", 0)) or 0)),
        fields={key: compact(value) for key, value in dict(payload.get("fields") or {}).items() if compact(value)},
        images=[
            {
                "src": compact(image.get("src")),
                "sourceUrl": compact(image.get("sourceUrl") or payload.get("url")),
                "sourceKind": compact(image.get("sourceKind") or payload.get("source_kind") or payload.get("sourceKind")),
                "attribution": compact(image.get("attribution") or payload.get("source_label") or payload.get("sourceLabel")),
                "title": compact(image.get("title")),
            }
            for image in list(payload.get("images") or [])
            if compact(image.get("src"))
        ],
    )


class RetrievalPipeline:
    def __init__(
        self,
        *,
        source_provider: SourceProvider,
        llm_client: LlmClient | None = None,
    ) -> None:
        self._source_provider = source_provider
        self._llm_client = llm_client
        self._normalizer = InputNormalizer()
        self._profile_resolver = ProfileResolver()

    def consume_access_events(self) -> list[dict[str, Any]]:
        return list(getattr(self._source_provider, "consume_access_events", lambda: [])())

    def get_access_summary(self) -> dict[str, Any]:
        return dict(getattr(self._source_provider, "get_access_summary", lambda: {})())

    async def aclose(self) -> None:
        close_source_provider = getattr(self._source_provider, "aclose", None)
        if callable(close_source_provider):
            await close_source_provider()

    async def retrieve(
        self,
        item: RetrievalItem,
        *,
        cancel_event: Any | None = None,
        deadline: float | None = None,
    ) -> ResultItemResponse:
        start_request_scope = getattr(self._source_provider, "start_request_scope", None)
        if callable(start_request_scope):
            start_request_scope()
        draft = self._normalizer.normalize(item)
        profile = self._profile_resolver.resolve(item)
        logs = [LogEntry(message="draft entry initialized", itemId=item.item_id)]
        warnings: list[str] = []
        records: list[SourceRecord] = []
        deadline_exceeded = False

        stages = [
            ("existing-link", self._source_provider.inspect_existing_links),
            ("high-quality", self._source_provider.search_high_quality),
            ("streaming", self._source_provider.search_streaming),
            ("fallback", self._source_provider.search_fallback),
        ]
        remaining_stage_weights = [STAGE_WEIGHTS.get(label, 1.0) for label, _ in stages]
        if self._llm_client is not None:
            remaining_stage_weights.append(STAGE_WEIGHTS["llm"])

        for index, (label, loader) in enumerate(stages, start=1):
            if is_cancelled(cancel_event):
                return canceled_result(item.item_id, logs, warnings)
            if should_skip_stage(label=label, records=records):
                logs.append(
                    LogEntry(
                        message=f"{label} stage skipped: strong resource candidates already collected",
                        itemId=item.item_id,
                    )
                )
                continue
            stage_timeout = calculate_stage_timeout(deadline, remaining_stage_weights[index - 1 :])
            if stage_timeout is not None and stage_timeout <= 0:
                deadline_exceeded = True
                warnings.append("检索截止时间已到，来源收集提前结束。")
                logs.append(LogEntry(message=f"{label} stage skipped: deadline reached", itemId=item.item_id, level="warning"))
                break
            try:
                payloads = await run_with_optional_timeout(loader(draft, profile), stage_timeout)
                records.extend(normalize_source_record(payload) for payload in payloads)
                logs.append(LogEntry(message=f"{label} stage collected {len(payloads)} records", itemId=item.item_id))
                warnings.extend(getattr(self._source_provider, "consume_warnings", lambda: [])())
            except TimeoutError:
                warnings.append(f"{label} 阶段超时。")
                logs.append(LogEntry(message=f"{label} stage timed out", itemId=item.item_id, level="warning"))
            except Exception as error:
                warnings.append(f"{label} 阶段失败：{error}")
                logs.append(LogEntry(message=f"{label} stage failed: {error}", itemId=item.item_id, level="warning"))

        synthesis: dict[str, Any] = {}
        if self._llm_client is not None and records and not is_cancelled(cancel_event):
            stage_timeout = calculate_stage_timeout(deadline, [STAGE_WEIGHTS["llm"]])
            minimum_timeout = getattr(self._llm_client, "minimum_synthesis_timeout_seconds", 0.0)
            allow_realtime_synthesis = getattr(self._llm_client, "allow_realtime_synthesis", True)
            if not allow_realtime_synthesis:
                logs.append(
                    LogEntry(
                        message="llm synthesis skipped for this model; realtime retrieval uses rule-based assembly",
                        itemId=item.item_id,
                    )
                )
            elif should_skip_llm_synthesis(records):
                logs.append(
                    LogEntry(
                        message="llm synthesis skipped: top candidate is already unambiguous",
                        itemId=item.item_id,
                    )
                )
            elif stage_timeout is not None and stage_timeout < minimum_timeout:
                logs.append(
                    LogEntry(
                        message=f"llm synthesis skipped: budget {stage_timeout:.1f}s is below required {minimum_timeout:.1f}s",
                        itemId=item.item_id,
                    )
                )
            elif stage_timeout is None or stage_timeout > 0:
                try:
                    synthesis = await run_with_optional_timeout(
                        self._llm_client.synthesize(draft, profile, records),
                        stage_timeout,
                    )
                    logs.append(LogEntry(message="llm synthesis completed", itemId=item.item_id))
                except TimeoutError:
                    warnings.append("LLM 归并超时。")
                    logs.append(LogEntry(message="llm synthesis timed out", itemId=item.item_id, level="warning"))
                except Exception as error:
                    warnings.append(f"LLM 归并失败：{error}")
                    logs.append(LogEntry(message=f"llm synthesis failed: {error}", itemId=item.item_id, level="warning"))

        if is_cancelled(cancel_event):
            return canceled_result(item.item_id, logs, warnings)

        result, evidence, link_candidates, image_candidates, field_warnings, confidence = self._assemble_result(
            draft=draft,
            records=records,
            notes=compact(synthesis.get("notes")),
            accepted_urls=[compact(url) for url in synthesis.get("acceptedUrls", []) if compact(url)],
        )
        warnings.extend(field_warnings)
        warnings.extend(str(entry) for entry in synthesis.get("warnings", []) if compact(entry))

        status = self._resolve_status(item, records, result, evidence)
        if deadline_exceeded and status == "not_found":
            status = "failed"
        if deadline_exceeded:
            logs.append(LogEntry(message="retrieval deadline reached", itemId=item.item_id, level="warning"))
        if status == "not_found":
            warnings.append("未找到可确认属于同一版本的可信来源。")
        if not result.notes and compact(synthesis.get("summary")):
            result.notes = compact(synthesis.get("summary"))

        return ResultItemResponse(
            itemId=item.item_id,
            status=status,
            confidence=confidence,
            warnings=dedupe_preserve_order(warnings),
            result=result,
            evidence=evidence,
            linkCandidates=link_candidates,
            imageCandidates=image_candidates,
            logs=logs,
        )

    def _assemble_result(
        self,
        *,
        draft: DraftRecordingEntry,
        records: list[SourceRecord],
        notes: str,
        accepted_urls: list[str],
    ) -> tuple[ResultPayload, list[EvidenceItem], list[LinkCandidate], list[ImageCandidate], list[str], float]:
        result = ResultPayload()
        if notes:
            result.notes = notes
        warnings: list[str] = []
        evidence: list[EvidenceItem] = []
        record_map = {compact(record.url): record for record in records if compact(record.url)}
        link_candidates = dedupe_link_candidates(
            sort_link_candidates(
                draft,
                [
                    LinkCandidate(
                        platform=record.platform or "other",
                        url=record.url,
                        title=record.title or draft.title,
                        sourceLabel=record.source_label,
                        confidence=round(record.same_recording_score, 2),
                    )
                    for record in records
                    if record.url and record.same_recording_score >= LOW_CONFIDENCE_THRESHOLD
                ],
                record_map,
            )
        )

        candidate_map: dict[str, list[FieldCandidate]] = defaultdict(list)
        confidences: list[float] = []
        raw_images: list[tuple[SourceRecord, dict[str, Any], float]] = []

        for record in records:
            record_confidence = compute_record_confidence(record)
            if record_confidence >= LOW_CONFIDENCE_THRESHOLD:
                confidences.append(record_confidence)
            for field, value in record.fields.items():
                if not value:
                    continue
                candidate_map[field].append(
                    FieldCandidate(
                        field=field,
                        value=value,
                        confidence=record_confidence,
                        source_url=record.url,
                        source_label=record.source_label,
                        accepted=record.same_recording_score >= SAME_RECORDING_THRESHOLD,
                    )
                )
            for image in record.images:
                raw_images.append((record, image, record_confidence))

        field_warning_map: dict[str, str] = {}
        for field, candidates in candidate_map.items():
            for candidate in candidates:
                evidence.append(
                    EvidenceItem(
                        field=field,
                        sourceUrl=candidate.source_url,
                        sourceLabel=candidate.source_label,
                        confidence=round(candidate.confidence, 2),
                        note="final" if candidate.accepted else "candidate-only",
                    )
                )

            top = pick_final_candidate(candidates)
            if top is None:
                field_warning_map[field] = f"{field} 未达到最终采纳阈值。"
                continue
            if field == "performanceDateText":
                result.performance_date_text = top.value
            elif field == "venueText":
                result.venue_text = top.value
            elif field == "albumTitle":
                result.album_title = top.value
            elif field == "label":
                result.label = top.value
            elif field == "releaseDate":
                result.release_date = top.value

        image_candidates = dedupe_image_candidates(
            [
                ImageCandidate(
                    src=image["src"],
                    sourceUrl=image.get("sourceUrl") or record.url,
                    sourceKind=image.get("sourceKind") or record.source_kind,
                    attribution=image.get("attribution") or record.source_label,
                    title=image.get("title") or record.title or draft.title,
                )
                for record, image, confidence in raw_images
                if image.get("src") and confidence >= LOW_CONFIDENCE_THRESHOLD
            ]
        )
        result.images = [
            image
            for image in image_candidates
            if any(
                compact(image.src) == compact(source_image.get("src")) and confidence >= FINAL_IMAGE_CONFIDENCE_THRESHOLD
                for _, source_image, confidence in raw_images
            )
        ][:3]
        if not result.images and image_candidates and link_candidates:
            winning_urls = {
                compact(candidate.url)
                for candidate in link_candidates
                if (candidate.confidence or 0) >= FINAL_LINK_CONFIDENCE_THRESHOLD
            }
            result.images = [image for image in image_candidates if compact(image.source_url) in winning_urls][:3]
        if not result.images and image_candidates:
            warnings.append("找到封面候选，但尚未达到最终采纳阈值。")

        accepted_url_set = {compact(url) for url in accepted_urls if compact(url)}
        result.links = [
            candidate
            for candidate in link_candidates
            if (candidate.confidence or 0) >= FINAL_LINK_CONFIDENCE_THRESHOLD or compact(candidate.url) in accepted_url_set
        ]
        ambiguous_upload_cluster = has_ambiguous_upload_cluster(draft, link_candidates)
        if result.links:
            top_link_confidence = max((candidate.confidence or 0) for candidate in result.links)
            title_only_collaboration_hint = has_title_only_collaboration_hint(draft)
            if title_only_collaboration_hint and len(result.links) >= 5:
                floor_delta = 0.32
            elif ambiguous_upload_cluster and is_sparse_upload_query(draft):
                floor_delta = 0.26
            else:
                floor_delta = 0.18 if ambiguous_upload_cluster else 0.08
            floor = max(FINAL_LINK_CONFIDENCE_THRESHOLD, top_link_confidence - floor_delta)
            filtered_links = [
                candidate
                for candidate in link_candidates
                if (candidate.confidence or 0) >= floor or compact(candidate.url) in accepted_url_set
            ]
            filtered_links = sort_link_candidates(
                draft,
                filtered_links,
                record_map,
                prefer_exactness=ambiguous_upload_cluster,
            )
            reference_year = extract_reference_year(draft)
            if reference_year:
                year_matched_links = [
                    candidate
                    for candidate in filtered_links
                    if not extract_conflicting_year(compact(candidate.title).lower(), reference_year)
                    or compact(candidate.url) in accepted_url_set
                ]
                if year_matched_links:
                    filtered_links = year_matched_links
            if ambiguous_upload_cluster and len(filtered_links) >= 3:
                best_exactness = max(candidate_title_quality_score(draft, compact(candidate.title)) for candidate in filtered_links)
                exactness_floor = max(0.03 if is_sparse_upload_query(draft) else 0.05, best_exactness - 0.05)
                filtered_links = [
                    candidate
                    for candidate in filtered_links
                    if candidate_title_quality_score(draft, compact(candidate.title)) >= exactness_floor
                    or compact(candidate.url) in accepted_url_set
                ]
            result.links = filtered_links[
                : determine_final_link_limit(
                    draft,
                    filtered_links,
                    accepted_url_count=len(accepted_url_set),
                    ambiguous_upload_cluster=ambiguous_upload_cluster,
                )
            ]
        if not result.links and accepted_url_set:
            result.links = sort_link_candidates(
                draft,
                [candidate for candidate in link_candidates if compact(candidate.url) in accepted_url_set],
                record_map,
            )[:2]
        if not result.links and link_candidates:
            dominant = pick_dominant_link_candidate(draft, sort_link_candidates(draft, link_candidates, record_map))
            if dominant is not None:
                result.links = [dominant]
        if not result.images and image_candidates and accepted_url_set:
            result.images = [image for image in image_candidates if compact(image.source_url) in accepted_url_set][:3]
        if result.links and not result.images and image_candidates:
            winning_urls = {compact(candidate.url) for candidate in result.links}
            result.images = [image for image in image_candidates if compact(image.source_url) in winning_urls][:3]
        if result.links:
            first_link = result.links[0]
            if not compact(result.album_title) and compact(first_link.title):
                result.album_title = compact(first_link.title)
            if not compact(result.label) and compact(first_link.source_label):
                result.label = compact(first_link.source_label)
        strongest_match = max((record.same_recording_score for record in records), default=0.0)
        if strongest_match >= FINAL_LINK_CONFIDENCE_THRESHOLD or result.links or accepted_url_set:
            self._carry_forward_trusted_input_fields(draft, result)
        warnings.extend(
            warning
            for field, warning in field_warning_map.items()
            if not has_result_value(result, field)
        )
        return result, evidence, link_candidates, image_candidates, warnings, round(max(confidences or [0.0]), 2)

    def _carry_forward_trusted_input_fields(
        self,
        draft: DraftRecordingEntry,
        result: ResultPayload,
    ) -> None:
        trusted_values = {
            "performanceDateText": compact(draft.performance_date_text),
            "venueText": compact(draft.venue_text),
            "albumTitle": compact(draft.album_title),
            "label": compact(draft.label),
            "releaseDate": compact(draft.release_date),
        }
        for field, value in trusted_values.items():
            if not value or has_result_value(result, field):
                continue
            if field == "performanceDateText":
                result.performance_date_text = value
            elif field == "venueText":
                result.venue_text = value
            elif field == "albumTitle":
                result.album_title = value
            elif field == "label":
                result.label = value
            elif field == "releaseDate":
                result.release_date = value

    def _resolve_status(
        self,
        item: RetrievalItem,
        records: list[SourceRecord],
        result: ResultPayload,
        evidence: list[EvidenceItem],
    ) -> str:
        if not records or max((record.same_recording_score for record in records), default=0.0) < LOW_CONFIDENCE_THRESHOLD:
            return "not_found"

        finalized_scalar_values = [
            result.performance_date_text,
            result.venue_text,
            result.album_title,
            result.label,
            result.release_date,
        ]
        has_final_links = bool(result.links)
        has_final_images = bool(result.images)
        has_final_data = any(compact(value) for value in finalized_scalar_values) or has_final_links or has_final_images or compact(result.notes)
        if not has_final_data and evidence:
            return "partial"

        unresolved_fields = [
            field
            for field in item.requested_fields
            if field in FINALIZABLE_FIELDS and not has_result_value(result, field)
        ]
        if unresolved_fields:
            return "partial"
        return "succeeded"


async def run_with_optional_timeout(awaitable: Any, timeout_seconds: float | None) -> Any:
    if timeout_seconds is None:
        return await awaitable
    try:
        return await asyncio.wait_for(awaitable, timeout=timeout_seconds)
    except asyncio.TimeoutError as error:
        raise TimeoutError from error


def calculate_stage_timeout(deadline: float | None, remaining_weights: list[float]) -> float | None:
    if deadline is None:
        return None
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        return 0.0
    total_weight = max(0.5, sum(remaining_weights) or 1.0)
    current_weight = max(0.3, remaining_weights[0] if remaining_weights else 1.0)
    return max(0.4, remaining * (current_weight / total_weight))


def is_cancelled(cancel_event: Any | None) -> bool:
    return bool(cancel_event is not None and cancel_event.is_set())


def canceled_result(item_id: str, logs: list[LogEntry], warnings: list[str]) -> ResultItemResponse:
    return ResultItemResponse(
        itemId=item_id,
        status="failed",
        confidence=0.0,
        warnings=dedupe_preserve_order([*warnings, "任务已取消。"]),
        result=ResultPayload(notes="检索在完成前已取消。"),
        evidence=[],
        linkCandidates=[],
        imageCandidates=[],
        logs=[*logs, LogEntry(message="retrieval canceled", itemId=item_id, level="warning")],
    )


def compute_record_confidence(record: SourceRecord) -> float:
    kind_bonus = {
        "existing-link": 0.12,
        "high-quality": 0.08,
        "streaming": 0.02,
        "search": 0.0,
        "fallback": 0.0,
    }.get(record.source_kind, 0.0)
    return max(0.0, min(0.99, record.same_recording_score * 0.7 + record.weight * 0.2 + kind_bonus))


def pick_final_candidate(candidates: list[FieldCandidate]) -> FieldCandidate | None:
    if not candidates:
        return None
    grouped: dict[str, list[FieldCandidate]] = defaultdict(list)
    for candidate in candidates:
        grouped[candidate.value].append(candidate)

    _, best_group = max(
        grouped.items(),
        key=lambda item: (
            len({candidate.source_label for candidate in item[1]}),
            max(candidate.confidence for candidate in item[1]),
        ),
    )
    top_confidence = max(candidate.confidence for candidate in best_group)
    corroborated = len({candidate.source_label for candidate in best_group}) >= 2
    if top_confidence >= FINAL_CONFIDENCE_THRESHOLD:
        return sorted(best_group, key=lambda candidate: candidate.confidence, reverse=True)[0]
    if corroborated:
        average_confidence = sum(candidate.confidence for candidate in best_group) / len(best_group)
        if average_confidence >= CORROBORATED_CONFIDENCE_THRESHOLD:
            return sorted(best_group, key=lambda candidate: candidate.confidence, reverse=True)[0]
    return None


def pick_dominant_link_candidate(draft: DraftRecordingEntry, candidates: list[LinkCandidate]) -> LinkCandidate | None:
    if not candidates:
        return None
    ordered = sorted(candidates, key=lambda candidate: candidate.confidence or 0.0, reverse=True)
    top = ordered[0]
    top_confidence = top.confidence or 0.0
    runner_up_confidence = ordered[1].confidence or 0.0 if len(ordered) > 1 else 0.0
    is_known_platform = compact(top.platform) in {"youtube", "bilibili", "apple_music", "spotify", "qobuz"}
    if top_confidence >= 0.58:
        return top
    top_exactness = candidate_title_quality_score(draft, compact(top.title))
    runner_up_exactness = (
        max(candidate_title_quality_score(draft, compact(candidate.title)) for candidate in ordered[1:])
        if len(ordered) > 1
        else -0.05
    )
    if top_confidence >= 0.5 and is_known_platform and top_confidence - runner_up_confidence >= 0.08:
        return top
    if top_confidence >= 0.5 and is_known_platform and top_exactness >= 0.1 and top_exactness - runner_up_exactness >= 0.03:
        return top
    if top_confidence >= 0.5 and is_known_platform and len(ordered) == 1:
        return top
    return None


def sort_link_candidates(
    draft: DraftRecordingEntry,
    candidates: list[LinkCandidate],
    record_map: dict[str, SourceRecord],
    *,
    prefer_exactness: bool = False,
) -> list[LinkCandidate]:
    return sorted(
        candidates,
        key=lambda candidate: (
            ambiguous_link_candidate_sort_key(draft, candidate, record_map.get(compact(candidate.url)))
            if prefer_exactness
            else link_candidate_sort_key(draft, candidate, record_map.get(compact(candidate.url)))
        ),
        reverse=True,
    )


def link_candidate_sort_key(
    draft: DraftRecordingEntry,
    candidate: LinkCandidate,
    record: SourceRecord | None,
) -> tuple[float, float, int, int]:
    confidence = candidate.confidence or 0.0
    title = compact(candidate.title)
    lowered = title.lower()
    exactness = candidate_title_quality_score(draft, title)
    if record is not None:
        if record.duration_seconds > 0:
            exactness += 0.03
        else:
            exactness -= 0.03
        if compact(record.uploader):
            exactness += 0.02
        else:
            exactness -= 0.02
        if record.view_count >= 8000:
            exactness += 0.06
        elif record.view_count >= 2000:
            exactness += 0.04
        elif record.view_count >= 500:
            exactness += 0.02
    if "new edition" in lowered or "remaster" in lowered or "restored" in lowered:
        exactness -= 0.08
    if "provided to youtube by" in lowered:
        exactness -= 0.08
    return (
        round(confidence + exactness, 4),
        round(exactness, 4),
        record.view_count if record is not None else 0,
        -len(title),
    )


def ambiguous_link_candidate_sort_key(
    draft: DraftRecordingEntry,
    candidate: LinkCandidate,
    record: SourceRecord | None,
) -> tuple[float, float, float, int]:
    title = compact(candidate.title)
    exactness = candidate_title_quality_score(draft, title)
    metadata_support = 0.0
    if record is not None:
        if record.duration_seconds > 0:
            metadata_support += 0.06
        else:
            metadata_support -= 0.08
        if compact(record.uploader):
            metadata_support += 0.04
        else:
            metadata_support -= 0.05
        if record.view_count >= 8000:
            metadata_support += 0.06
        elif record.view_count >= 2000:
            metadata_support += 0.04
        elif record.view_count >= 500:
            metadata_support += 0.02
    confidence = min(candidate.confidence or 0.0, 0.88)
    return (
        round(exactness + metadata_support, 4),
        round(confidence, 4),
        round((candidate.confidence or 0.0) + exactness, 4),
        record.view_count if record is not None else 0,
    )


def candidate_title_quality_score(draft: DraftRecordingEntry, title: str) -> float:
    lowered = compact(title).lower()
    if not lowered:
        return -0.05
    score = 0.0
    year = extract_reference_year(draft)
    if year and year in lowered:
        score += 0.05
    elif year and extract_conflicting_year(lowered, year):
        score -= 0.05
    work_aliases = build_candidate_work_anchor_terms(draft)
    if any(alias in lowered for alias in work_aliases):
        score += 0.03
    if title_matches_catalogue(draft, lowered):
        score += 0.05
    elif should_require_catalogue_hint(draft, lowered):
        score -= 0.02
    if candidate_mentions_primary_and_secondary(draft, lowered):
        score += 0.04
    elif candidate_mentions_any_lead(draft, lowered):
        score += 0.01
    if any(marker in lowered for marker in ("new edition", "restored", "remaster", "reissue", "alt take")):
        score -= 0.08
    if any(marker in lowered for marker in ("blu-ray", "bluray", "bd版", "蓝光", "「bd」", "[bd]", "(bd)")):
        score -= 0.06
    return score


def title_matches_catalogue(draft: DraftRecordingEntry, lowered_title: str) -> bool:
    catalogue = compact(draft.catalogue).lower()
    if not catalogue:
        return False
    normalized_catalogue = re.sub(r"\s+", "", catalogue)
    normalized_title = re.sub(r"\s+", "", lowered_title)
    return catalogue in lowered_title or normalized_catalogue in normalized_title


def should_require_catalogue_hint(draft: DraftRecordingEntry, lowered_title: str) -> bool:
    if not compact(draft.catalogue):
        return False
    work_markers = ("concerto", "symphony", "sonata", "quartet", "trio", "op.")
    return any(marker in lowered_title for marker in work_markers)


def build_candidate_work_anchor_terms(draft: DraftRecordingEntry) -> set[str]:
    values: set[str] = set()
    for value in (compact(draft.work_title_latin), compact(draft.work_title), compact(draft.catalogue)):
        if not value:
            continue
        lowered = value.lower()
        values.add(lowered)
        latin_alias = build_latin_work_alias(value)
        if latin_alias:
            values.add(latin_alias.lower())
        stripped = re.sub(r"\b(?:op|k|bwv|hob|d|wab)\.?\s*\d+[a-z]?\b", "", lowered, flags=re.I).strip(" ,.;:-")
        if stripped:
            values.add(stripped)
    return {value for value in values if len(value) >= 4}


def candidate_mentions_primary_and_secondary(draft: DraftRecordingEntry, lowered_title: str) -> bool:
    primary = candidate_mentions_names(lowered_title, getattr(draft, "primary_names_latin", []) or getattr(draft, "primary_names", []))
    secondary = candidate_mentions_names(
        lowered_title,
        getattr(draft, "secondary_names_latin", []) or getattr(draft, "secondary_names", []),
    )
    return primary and secondary


def candidate_mentions_any_lead(draft: DraftRecordingEntry, lowered_title: str) -> bool:
    lead_values = [
        *getattr(draft, "primary_names_latin", []),
        *getattr(draft, "primary_names", []),
        *getattr(draft, "secondary_names_latin", []),
        *getattr(draft, "secondary_names", []),
        *draft.lead_names_latin,
        *draft.lead_names,
    ]
    return candidate_mentions_names(lowered_title, lead_values)


def candidate_mentions_names(lowered_title: str, values: list[str]) -> bool:
    for value in values:
        tokens = tokenize_person_name(value)
        if not tokens:
            continue
        surname = tokens[-1].lower()
        if len(surname) >= 3 and surname in lowered_title:
            return True
    return False


def extract_reference_year(draft: DraftRecordingEntry) -> str:
    for value in (draft.performance_date_text, draft.title, draft.raw_text):
        match = re.search(r"(17|18|19|20)\d{2}", compact(value))
        if match:
            return match.group(0)
    return ""


def extract_conflicting_year(lowered_title: str, reference_year: str) -> bool:
    years = set(re.findall(r"(?:17|18|19|20)\d{2}", lowered_title))
    return bool(years and reference_year not in years)


def has_ambiguous_upload_cluster(draft: DraftRecordingEntry, candidates: list[LinkCandidate]) -> bool:
    if len(candidates) < 3:
        return False
    top_confidence = candidates[0].confidence or 0.0
    top_platform = compact(candidates[0].platform)
    if top_platform not in {"youtube", "bilibili"}:
        return False
    sparse_query = is_sparse_upload_query(draft)
    confidence_window = 0.25 if sparse_query else 0.2
    reference_floor = 0.04 if sparse_query else 0.05
    near_top = [
        candidate
        for candidate in candidates
        if compact(candidate.platform) == top_platform
        and (candidate.confidence or 0.0) >= max(FINAL_LINK_CONFIDENCE_THRESHOLD, top_confidence - confidence_window)
    ]
    if len(near_top) < 3:
        return False
    exactness_scores = [candidate_title_quality_score(draft, compact(candidate.title)) for candidate in near_top]
    reference_hits = sum(1 for score in exactness_scores if score >= reference_floor)
    if len(near_top) >= 3 and reference_hits >= 2 and (max(exactness_scores, default=0.0) - min(exactness_scores, default=0.0)) >= 0.05:
        return True
    if len(near_top) >= 4 and reference_hits >= 2:
        return True
    return reference_hits >= 3


def determine_final_link_limit(
    draft: DraftRecordingEntry,
    candidates: list[LinkCandidate],
    *,
    accepted_url_count: int = 0,
    ambiguous_upload_cluster: bool = False,
) -> int:
    if not candidates:
        return 2
    collaboration_hint = has_title_only_collaboration_hint(draft)
    if accepted_url_count >= 2:
        if collaboration_hint and len(candidates) >= 5:
            return 5
        return min(4, max(2, accepted_url_count))
    if ambiguous_upload_cluster:
        if is_sparse_upload_query(draft):
            return 5
        return 4
    top_confidence = candidates[0].confidence or 0.0
    close_ties = [
        candidate
        for candidate in candidates
        if abs((candidate.confidence or 0.0) - top_confidence) <= 0.01
    ]
    if collaboration_hint and len(candidates) >= 5 and len(close_ties) >= 3:
        return 5
    if not has_explicit_year(draft.performance_date_text) and len(close_ties) > 1:
        return min(4, max(2, len(close_ties)))
    if len(close_ties) >= 3:
        return min(4, len(close_ties))
    return 2


def should_skip_stage(*, label: str, records: list[SourceRecord]) -> bool:
    if label != "fallback":
        return False
    strong_records = [
        record
        for record in records
        if compact(record.url)
        and record.platform in {"youtube", "bilibili", "apple_music", "spotify", "qobuz"}
        and record.same_recording_score >= 0.6
    ]
    if any(record.same_recording_score >= 0.72 for record in strong_records):
        return True
    return len(strong_records) >= 2


def should_skip_llm_synthesis(records: list[SourceRecord]) -> bool:
    scores = sorted((record.same_recording_score for record in records if compact(record.url)), reverse=True)
    if not scores:
        return True
    if scores[0] < 0.88:
        return False
    second_best = scores[1] if len(scores) > 1 else 0.0
    return scores[0] - second_best >= 0.12 and second_best <= 0.45


def has_explicit_year(value: str) -> bool:
    return bool(re.search(r"(17|18|19|20)\d{2}", compact(value)))


def is_sparse_upload_query(draft: DraftRecordingEntry) -> bool:
    if has_explicit_year(draft.source_line):
        return False
    query_leads = dedupe_preserve_order([*draft.query_lead_names_latin, *draft.query_lead_names])
    if len(query_leads) > 1:
        return False
    if draft.secondary_names or draft.secondary_names_latin:
        return False
    if draft.ensemble_names or draft.ensemble_names_latin:
        return False
    return True


def has_title_only_collaboration_hint(draft: DraftRecordingEntry) -> bool:
    if has_explicit_year(draft.source_line):
        return False
    if not (has_collaboration_marker(draft.title) or " - " in compact(draft.title)):
        return False
    return bool(draft.primary_names or draft.primary_names_latin or draft.lead_names or draft.lead_names_latin)


def has_result_value(result: ResultPayload, field: str) -> bool:
    mapping = {
        "performanceDateText": compact(result.performance_date_text),
        "venueText": compact(result.venue_text),
        "albumTitle": compact(result.album_title),
        "label": compact(result.label),
        "releaseDate": compact(result.release_date),
        "notes": compact(result.notes),
        "links": "yes" if result.links else "",
        "images": "yes" if result.images else "",
    }
    return bool(mapping.get(field, ""))


def dedupe_preserve_order(values: list[str]) -> list[str]:
    seen: set[str] = set()
    items: list[str] = []
    for value in values:
        normalized = compact(value)
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        items.append(normalized)
    return items


def dedupe_link_candidates(items: list[LinkCandidate]) -> list[LinkCandidate]:
    seen: set[str] = set()
    unique: list[LinkCandidate] = []
    for item in items:
        url = compact(item.url)
        if not url:
            continue
        key = url.lower()
        if key in seen:
            continue
        seen.add(key)
        unique.append(item)
    return unique


def dedupe_image_candidates(items: list[ImageCandidate]) -> list[ImageCandidate]:
    seen: set[str] = set()
    unique: list[ImageCandidate] = []
    for item in items:
        src = compact(item.src)
        if not src:
            continue
        key = src.lower()
        if key in seen:
            continue
        seen.add(key)
        unique.append(item)
    return unique


def infer_people_from_source_line(source_line: str) -> tuple[list[str], list[str]]:
    segments = [compact(part) for part in re.split(r"[|\n]", source_line or "") if compact(part)]
    if not segments:
        return [], []
    leads: list[str] = []
    groups: list[str] = []
    if segments and not looks_like_year_or_work(segments[0]):
        leads.append(segments[0])
    if len(segments) >= 2 and not looks_like_year_or_work(segments[1]):
        groups.append(segments[1])
    return leads, groups


def infer_people_from_title(title: str) -> list[str]:
    people, _, _ = infer_title_entities(title)
    return people


def infer_title_entities(title: str) -> tuple[list[str], list[str], str]:
    normalized = compact(title)
    if not normalized:
        return [], [], ""
    date_hint = extract_title_date_hint(normalized)
    people: list[str] = []
    groups: list[str] = []
    for part in split_title_segments(normalized):
        value = compact(part.strip(" ,;|"))
        if not value:
            continue
        if date_hint and date_hint in value:
            continue
        if looks_like_ensemble_name(value):
            groups.append(value)
            continue
        if looks_like_year_or_work(value):
            continue
        if looks_like_title_person(value):
            people.append(value)
    return dedupe_preserve_order(people[:3]), dedupe_preserve_order(groups[:2]), date_hint


def split_title_segments(value: str) -> list[str]:
    normalized = compact(value)
    if not normalized:
        return []
    return [part for part in re.split(r"\s*(?:&|/| and | with | feat\.?| - )\s*", normalized, flags=re.I) if compact(part)]


def extract_title_date_hint(title: str) -> str:
    normalized = compact(title)
    if not normalized:
        return ""
    patterns = [
        r"\b(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec)[a-z]*\.?\s+\d{1,2},\s+\d{4}\b",
        r"\b(?:early|mid|late)\s+'?\d{2}s\b",
        r"\b(?:19|20)\d{2}\b",
    ]
    for pattern in patterns:
        match = re.search(pattern, normalized, flags=re.I)
        if match:
            return compact(match.group(0))
    return ""


def extract_title_performance_context(title: str) -> str:
    normalized = compact(title)
    if not normalized:
        return ""
    for part in split_title_segments(normalized):
        value = compact(part.strip(" ,;|"))
        if not value:
            continue
        year_hint = extract_title_date_hint(value)
        if not year_hint or compact(value) == year_hint:
            continue
        return value
    return ""


def looks_like_ensemble_name(value: str) -> bool:
    lowered = compact(value).lower()
    return any(
        token in lowered
        for token in (
            "orchestra",
            "philharmonic",
            "symphony orchestra",
            "ensemble",
            "choir",
            "chorus",
            "quartet",
            "trio",
            "乐团",
            "愛樂",
            "爱乐",
            "交响乐团",
            "管弦乐团",
            "合唱团",
            "四重奏",
            "三重奏",
        )
    )


def looks_like_title_person(value: str) -> bool:
    tokens = tokenize_person_name(value)
    if contains_cjk(value):
        return bool(tokens)
    if len(tokens) >= 2:
        return True
    return len(tokens) == 1 and len(tokens[0]) >= 4 and tokens[0][0].isalpha()


def person_variant_matches(left: str, right: str) -> bool:
    left_norm = re.sub(r"[^A-Za-z\u4e00-\u9fff]+", "", compact(left)).lower()
    right_norm = re.sub(r"[^A-Za-z\u4e00-\u9fff]+", "", compact(right)).lower()
    if not left_norm or not right_norm:
        return False
    return left_norm == right_norm or left_norm in right_norm or right_norm in left_norm


def tokenize_person_name(value: str) -> list[str]:
    return [token for token in re.split(r"[^A-Za-z\u4e00-\u9fff]+", compact(value)) if token]


def has_collaboration_marker(value: str) -> bool:
    normalized = compact(value).lower()
    return any(marker in normalized for marker in ("&", " / ", " and ", " with ", "、"))


def looks_like_year_or_work(value: str) -> bool:
    lowered = compact(value).lower()
    return bool(
        re.search(r"(19\d{2}|20\d{2})", lowered)
        or any(token in lowered for token in ("symphony", "concerto", "sonata", "opera", "交响曲", "协奏曲", "奏鸣曲", "歌剧"))
    )
