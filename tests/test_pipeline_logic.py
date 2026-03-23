from __future__ import annotations

import asyncio
import time

from app.models.protocol import CreateJobRequest
from app.services.http_sources import HttpSourceProvider
from app.services.pipeline import InputNormalizer, ProfileResolver, RetrievalPipeline, build_latin_work_alias, build_queries
from tests.fixtures import sample_request


class FakeSourceProvider:
    async def inspect_existing_links(self, draft, profile):
        return [
            {
                "url": "https://archive.example/kleiber-1975",
                "source_label": "Existing Link",
                "source_kind": "existing-link",
                "title": "Beethoven Symphony No. 5 - Kleiber Vienna 1975",
                "description": "Live recording in Vienna 1975. Deutsche Grammophon release 1976.",
                "platform": "archive",
                "weight": 1.0,
                "same_recording_score": 0.95,
                "fields": {
                    "performanceDateText": "1975",
                    "venueText": "Vienna",
                    "label": "Deutsche Grammophon",
                    "releaseDate": "1976",
                    "albumTitle": "Beethoven: Symphony No. 5",
                },
                "images": [
                    {
                        "src": "https://archive.example/images/kleiber-1975.jpg",
                        "title": "Cover",
                        "sourceUrl": "https://archive.example/kleiber-1975",
                        "sourceKind": "existing-link",
                    }
                ],
            }
        ]

    async def search_high_quality(self, draft, profile):
        return [
            {
                "url": "https://catalog.example/kleiber-1975",
                "source_label": "Catalog",
                "source_kind": "high-quality",
                "title": "Beethoven: Symphony No. 5 / Kleiber / Vienna Philharmonic",
                "description": "Recorded live in Vienna, 1975.",
                "platform": "other",
                "weight": 0.9,
                "same_recording_score": 0.92,
                "fields": {
                    "performanceDateText": "1975",
                    "venueText": "Vienna",
                    "label": "Deutsche Grammophon",
                },
            }
        ]

    async def search_streaming(self, draft, profile):
        return [
            {
                "url": "https://stream.example/kleiber-1975",
                "source_label": "Streaming",
                "source_kind": "streaming",
                "title": "Kleiber Beethoven 5 Vienna 1975",
                "description": "Live in Vienna 1975.",
                "platform": "youtube",
                "weight": 0.75,
                "same_recording_score": 0.88,
                "fields": {
                    "albumTitle": "Beethoven: Symphony No. 5",
                },
            }
        ]

    async def search_fallback(self, draft, profile):
        return []


class FakeLlm:
    async def synthesize(self, draft, profile, records):
        return {
            "notes": "已确认属于同一版本，发行信息由已有链接与目录页交叉支持。",
            "warnings": ["封面仍待进一步核对"],
            "summary": "关键字段较完整，但封面仍建议人工复核。",
        }


class WeakSourceProvider:
    async def inspect_existing_links(self, draft, profile):
        return []

    async def search_high_quality(self, draft, profile):
        return [
            {
                "url": "https://blog.example/speculative",
                "source_label": "Speculative Blog",
                "source_kind": "high-quality",
                "title": "Possibly the same recording",
                "description": "Maybe 1974 or 1975.",
                "platform": "other",
                "weight": 0.35,
                "same_recording_score": 0.55,
                "fields": {
                    "venueText": "Vienna",
                },
            }
        ]

    async def search_streaming(self, draft, profile):
        return []

    async def search_fallback(self, draft, profile):
        return []


class SlowSourceProvider:
    async def inspect_existing_links(self, draft, profile):
        await asyncio.sleep(0.4)
        return []

    async def search_high_quality(self, draft, profile):
        await asyncio.sleep(0.4)
        return []

    async def search_streaming(self, draft, profile):
        await asyncio.sleep(0.4)
        return []

    async def search_fallback(self, draft, profile):
        await asyncio.sleep(0.4)
        return []


class ClosableSourceProvider(FakeSourceProvider):
    def __init__(self) -> None:
        self.closed = False

    async def aclose(self) -> None:
        self.closed = True


def test_pipeline_writes_high_confidence_fields_to_result_and_keeps_candidates() -> None:
    request = CreateJobRequest.model_validate(sample_request())
    pipeline = RetrievalPipeline(source_provider=FakeSourceProvider(), llm_client=FakeLlm())

    result = asyncio.run(pipeline.retrieve(request.items[0]))

    assert result.status == "succeeded"
    assert result.result.performance_date_text == "1975"
    assert result.result.venue_text == "Vienna"
    assert result.result.label == "Deutsche Grammophon"
    assert result.result.release_date == "1976"
    assert result.result.notes == "已确认属于同一版本，发行信息由已有链接与目录页交叉支持。"
    assert result.result.images
    assert result.result.images[0].src == "https://archive.example/images/kleiber-1975.jpg"
    assert any(candidate.url == "https://stream.example/kleiber-1975" for candidate in result.link_candidates)
    assert any(evidence.field == "label" for evidence in result.evidence)
    assert "封面仍待进一步核对" in result.warnings


def test_pipeline_keeps_low_confidence_field_as_candidate_only() -> None:
    request = CreateJobRequest.model_validate(sample_request())
    pipeline = RetrievalPipeline(source_provider=WeakSourceProvider(), llm_client=None)

    result = asyncio.run(pipeline.retrieve(request.items[0]))

    assert result.status == "partial"
    assert result.result.venue_text is None
    assert any(candidate.url == "https://blog.example/speculative" for candidate in result.link_candidates)
    assert result.result.links == []
    assert any(evidence.field == "venueText" for evidence in result.evidence)
    assert any("未达到最终采纳阈值" in warning for warning in result.warnings)


def test_pipeline_respects_deadline_and_returns_without_hanging() -> None:
    request = CreateJobRequest.model_validate(sample_request())
    pipeline = RetrievalPipeline(source_provider=SlowSourceProvider(), llm_client=None)
    deadline = time.monotonic() + 0.2

    result = asyncio.run(pipeline.retrieve(request.items[0], deadline=deadline))

    assert result.status in {"failed", "not_found"}
    assert any("截止时间" in warning or "超时" in warning for warning in result.warnings)


def test_profile_resolver_prioritizes_work_person_group_and_year_queries() -> None:
    payload = sample_request()
    payload["items"][0]["seed"]["workTitleLatin"] = "Symphony No. 1 in C Minor"
    payload["items"][0]["seed"]["catalogue"] = "Op.68"
    request = CreateJobRequest.model_validate(payload)

    profile = ProfileResolver().resolve(request.items[0])

    assert profile.queries
    assert any("Symphony No. 1 in C Minor Op.68" in query for query in profile.queries)
    assert any("Conductor 1" in query for query in profile.queries)
    assert any("Orchestra 1" in query for query in profile.queries)


def test_profile_resolver_adds_people_and_year_fallback_queries_for_non_latin_input() -> None:
    payload = sample_request()
    payload["items"][0]["sourceLine"] = "柴可夫斯基 | 第五交响曲 | Rudolf Kempe | London Symphony Orchestra | 1964"
    payload["items"][0]["seed"]["title"] = "Rudolf Kempe - London Symphony Orchestra - 第五交响曲 - 1964"
    payload["items"][0]["seed"]["composerName"] = "柴可夫斯基"
    payload["items"][0]["seed"]["composerNameLatin"] = ""
    payload["items"][0]["seed"]["workTitle"] = "第五交响曲"
    payload["items"][0]["seed"]["workTitleLatin"] = ""
    payload["items"][0]["seed"]["catalogue"] = ""
    payload["items"][0]["seed"]["performanceDateText"] = "1964"
    payload["items"][0]["seed"]["credits"] = [
        {"role": "conductor", "displayName": "Rudolf Kempe", "label": "Rudolf Kempe"},
        {"role": "orchestra", "displayName": "London Symphony Orchestra", "label": "London Symphony Orchestra"},
    ]
    request = CreateJobRequest.model_validate(payload)

    profile = ProfileResolver().resolve(request.items[0])

    assert "Rudolf Kempe London Symphony Orchestra 1964" in profile.queries
    assert "Rudolf Kempe 1964" in profile.queries


def test_profile_resolver_adds_people_only_query_when_group_missing() -> None:
    payload = sample_request()
    payload["items"][0]["sourceLine"] = "柴可夫斯基 | 第五交响曲 | Albert Coates | - | 1922"
    payload["items"][0]["seed"]["title"] = "Albert Coates - 第五交响曲 - 1922"
    payload["items"][0]["seed"]["composerName"] = "柴可夫斯基"
    payload["items"][0]["seed"]["composerNameLatin"] = ""
    payload["items"][0]["seed"]["workTitle"] = "第五交响曲"
    payload["items"][0]["seed"]["workTitleLatin"] = ""
    payload["items"][0]["seed"]["catalogue"] = ""
    payload["items"][0]["seed"]["performanceDateText"] = "1922"
    payload["items"][0]["seed"]["credits"] = [
        {"role": "conductor", "displayName": "Albert Coates", "label": "Albert Coates"},
    ]
    request = CreateJobRequest.model_validate(payload)

    profile = ProfileResolver().resolve(request.items[0])

    assert "Albert Coates 1922" in profile.queries


def test_build_latin_work_alias_generates_english_alias_from_chinese_work_title() -> None:
    assert build_latin_work_alias("第五交响曲") == "Symphony No. 5"
    assert build_latin_work_alias("第五协奏曲") == "Concerto No. 5"
    assert build_latin_work_alias("第一奏鸣曲") == "Sonata No. 1"


def test_profile_resolver_builds_latin_queries_for_sparse_ui_style_input() -> None:
    payload = sample_request()
    payload["items"][0]["sourceLine"] = "柴可夫斯基 | 第五交响曲 op.64 | monteux | BSO | -"
    payload["items"][0]["seed"]["title"] = "monteux - BSO - 第五交响曲"
    payload["items"][0]["seed"]["composerName"] = "柴可夫斯基"
    payload["items"][0]["seed"]["composerNameLatin"] = ""
    payload["items"][0]["seed"]["workTitle"] = "第五交响曲"
    payload["items"][0]["seed"]["workTitleLatin"] = ""
    payload["items"][0]["seed"]["catalogue"] = "op.64"
    payload["items"][0]["seed"]["performanceDateText"] = ""
    payload["items"][0]["seed"]["credits"] = [
        {"role": "conductor", "displayName": "monteux", "label": "monteux"},
        {"role": "orchestra", "displayName": "BSO", "label": "BSO"},
    ]
    request = CreateJobRequest.model_validate(payload)

    profile = ProfileResolver().resolve(request.items[0])

    assert "Symphony No. 5 op.64 monteux BSO" in profile.latin_queries


def test_profile_resolver_builds_role_aware_concerto_queries() -> None:
    payload = sample_request()
    payload["items"][0]["workTypeHint"] = "concerto"
    payload["items"][0]["sourceLine"] = "Schumann | Piano Concerto, Op.54 | Annie Fischer | Kletzki | Budapest Philharmonic Orchestra | 1960"
    payload["items"][0]["seed"]["title"] = "Annie Fischer & Kletzki"
    payload["items"][0]["seed"]["composerName"] = "舒曼"
    payload["items"][0]["seed"]["composerNameLatin"] = "Robert Schumann"
    payload["items"][0]["seed"]["workTitle"] = "a小调钢琴协奏曲"
    payload["items"][0]["seed"]["workTitleLatin"] = "Piano Concerto, Op.54"
    payload["items"][0]["seed"]["catalogue"] = "Op.54"
    payload["items"][0]["seed"]["performanceDateText"] = "1960"
    payload["items"][0]["seed"]["credits"] = [
        {"role": "soloist", "displayName": "安妮·费舍尔", "label": "Annie Fischer"},
        {"role": "conductor", "displayName": "克列茨基", "label": "Kletzki"},
        {"role": "orchestra", "displayName": "布达佩斯爱乐乐团", "label": "Budapest Philharmonic Orchestra"},
    ]
    request = CreateJobRequest.model_validate(payload)

    profile = ProfileResolver().resolve(request.items[0])

    assert any("Annie Fischer Kletzki" in query for query in profile.latin_queries)
    assert any("Budapest Philharmonic Orchestra" in query for query in profile.latin_queries)
    assert "Annie Fischer Kletzki" in profile.latin_queries[0]


def test_input_normalizer_assigns_second_chamber_soloist_to_secondary_slot() -> None:
    payload = sample_request()
    payload["items"][0]["workTypeHint"] = "chamber_solo"
    payload["items"][0]["sourceLine"] = "Beethoven | Violin Sonata No.5, Op.24 | Jean Fournier | Ginette Doyen | -"
    payload["items"][0]["seed"]["title"] = "Jean Fournier & Ginette Doyen"
    payload["items"][0]["seed"]["composerName"] = "贝多芬"
    payload["items"][0]["seed"]["composerNameLatin"] = "Ludwig van Beethoven"
    payload["items"][0]["seed"]["workTitle"] = "第5号小提琴奏鸣曲“春天”"
    payload["items"][0]["seed"]["workTitleLatin"] = "Violin Sonata No.5, Op.24"
    payload["items"][0]["seed"]["catalogue"] = "Op.24"
    payload["items"][0]["seed"]["credits"] = [
        {"role": "soloist", "displayName": "让·富尼埃", "label": "Jean Fournier"},
        {"role": "soloist", "displayName": "吉内特·多延", "label": "Ginette Doyen"},
    ]
    request = CreateJobRequest.model_validate(payload)

    draft = InputNormalizer().normalize(request.items[0])

    assert draft.primary_names == ["让·富尼埃"]
    assert draft.secondary_names == ["吉内特·多延"]
    assert "Jean Fournier Ginette Doyen" in draft.query_lead_names_latin


def test_input_normalizer_extracts_embedded_english_aliases_from_credit_display_name() -> None:
    payload = sample_request()
    payload["items"][0]["seed"]["credits"] = [
        {
            "role": "soloist",
            "displayName": "Александр Яковлевич Могилевский, EN: Alexander Yakovlevich Mogilevsky",
            "label": "小提琴",
        },
        {
            "role": "orchestra",
            "displayName": "Budapesti Filharmóniai Társaság Zenekara (EN: Budapest Philharmonic Orchestra CHN: 布达佩斯爱乐乐团)",
            "label": "乐团",
        },
    ]
    request = CreateJobRequest.model_validate(payload)

    draft = InputNormalizer().normalize(request.items[0])

    assert "Alexander Yakovlevich Mogilevsky" in draft.lead_names_latin
    assert all("EN:" not in value for value in draft.lead_names)
    assert "Budapest Philharmonic Orchestra" in draft.ensemble_names_latin
    assert all("EN:" not in value for value in draft.ensemble_names)


def test_input_normalizer_infers_missing_chamber_collaborator_from_title() -> None:
    payload = sample_request()
    payload["items"][0]["workTypeHint"] = "chamber_solo"
    payload["items"][0]["sourceLine"] = "Beethoven | Violin Sonata No.5, Op.24 | Jean Fournier | - | -"
    payload["items"][0]["seed"]["title"] = "Jean Fournier & Ginette Doyen"
    payload["items"][0]["seed"]["composerName"] = "Beethoven"
    payload["items"][0]["seed"]["composerNameLatin"] = "Ludwig van Beethoven"
    payload["items"][0]["seed"]["workTitle"] = "Violin Sonata No.5, Op.24"
    payload["items"][0]["seed"]["workTitleLatin"] = "Violin Sonata No.5, Op.24"
    payload["items"][0]["seed"]["catalogue"] = "Op.24"
    payload["items"][0]["seed"]["credits"] = [
        {"role": "soloist", "displayName": "Jean Fournier", "label": "Jean Fournier"},
    ]
    request = CreateJobRequest.model_validate(payload)

    draft = InputNormalizer().normalize(request.items[0])

    assert "Ginette Doyen" in draft.secondary_names_latin
    assert "Jean Fournier Ginette Doyen" in draft.query_lead_names_latin


def test_input_normalizer_recovers_concerto_collaborator_group_and_date_from_title() -> None:
    payload = sample_request()
    payload["items"][0]["workTypeHint"] = "concerto"
    payload["items"][0]["sourceLine"] = "Ludwig van Beethoven | Violin Concerto in D major, Op.61 | Jascha Heifetz | -"
    payload["items"][0]["seed"]["title"] = "托斯卡尼尼 - 海菲兹 - NBC Symphony Orchestra - March 11, 1940, in Studio 8H, Radio City"
    payload["items"][0]["seed"]["composerName"] = "贝多芬"
    payload["items"][0]["seed"]["composerNameLatin"] = "Ludwig van Beethoven"
    payload["items"][0]["seed"]["workTitle"] = "D大调小提琴协奏曲"
    payload["items"][0]["seed"]["workTitleLatin"] = "Violin Concerto in D major, Op.61"
    payload["items"][0]["seed"]["catalogue"] = "Op.61"
    payload["items"][0]["seed"]["performanceDateText"] = ""
    payload["items"][0]["seed"]["credits"] = [
        {"role": "soloist", "displayName": "亚莎·海菲兹", "label": "Jascha Heifetz"},
    ]
    request = CreateJobRequest.model_validate(payload)

    draft = InputNormalizer().normalize(request.items[0])

    assert "托斯卡尼尼" in draft.secondary_names
    assert "NBC Symphony Orchestra" in draft.ensemble_names_latin
    assert draft.performance_date_text == "March 11, 1940"


def test_build_queries_keeps_composer_work_lead_date_combo_for_sparse_html_search() -> None:
    queries = build_queries(
        work_query="spring",
        composer_query="Ludwig van Beethoven",
        lead_terms=["Jean Fournier"],
        ensemble_terms=[],
        title="Jean Fournier - early '50s",
        performance_date_text="early '50s",
    )

    assert "Ludwig van Beethoven spring Jean Fournier early '50s" in queries


def test_pipeline_promotes_confident_links_and_associated_images_to_result() -> None:
    class LinkOnlySourceProvider:
        async def inspect_existing_links(self, draft, profile):
            return []

        async def search_high_quality(self, draft, profile):
            return []

        async def search_streaming(self, draft, profile):
            return [
                {
                    "url": "https://stream.example/right",
                    "source_label": "Streaming",
                    "source_kind": "streaming",
                    "title": "Exact Recording",
                    "description": "Exact same recording",
                    "platform": "youtube",
                    "weight": 0.9,
                    "same_recording_score": 0.92,
                    "fields": {},
                    "images": [
                        {
                            "src": "https://stream.example/right.jpg",
                            "sourceUrl": "https://stream.example/right",
                            "sourceKind": "streaming",
                            "title": "Exact Recording",
                        }
                    ],
                }
            ]

        async def search_fallback(self, draft, profile):
            return []

    request = CreateJobRequest.model_validate(sample_request())
    pipeline = RetrievalPipeline(source_provider=LinkOnlySourceProvider(), llm_client=None)

    result = asyncio.run(pipeline.retrieve(request.items[0]))

    assert result.status == "partial"
    assert result.result.links
    assert result.result.links[0].url == "https://stream.example/right"
    assert result.result.images
    assert result.result.images[0].src == "https://stream.example/right.jpg"


def test_pipeline_keeps_trusted_input_performance_date_when_search_confirms_recording() -> None:
    class MatchingSourceProvider:
        async def inspect_existing_links(self, draft, profile):
            return []

        async def search_high_quality(self, draft, profile):
            return []

        async def search_streaming(self, draft, profile):
            return [
                {
                    "url": "https://stream.example/right",
                    "source_label": "Streaming",
                    "source_kind": "streaming",
                    "title": "Exact Recording",
                    "description": "Same performers, no explicit year.",
                    "platform": "youtube",
                    "weight": 0.8,
                    "same_recording_score": 0.9,
                    "fields": {},
                    "images": [],
                }
            ]

        async def search_fallback(self, draft, profile):
            return []

    request = CreateJobRequest.model_validate(sample_request())
    pipeline = RetrievalPipeline(source_provider=MatchingSourceProvider(), llm_client=None)

    result = asyncio.run(pipeline.retrieve(request.items[0]))

    assert result.result.performance_date_text == "1975"
    assert not any("performanceDateText" in warning for warning in result.warnings)


def test_pipeline_only_promotes_top_tier_links_into_final_result() -> None:
    class MixedConfidenceSourceProvider:
        async def inspect_existing_links(self, draft, profile):
            return []

        async def search_high_quality(self, draft, profile):
            return []

        async def search_streaming(self, draft, profile):
            return [
                {
                    "url": "https://stream.example/right",
                    "source_label": "Streaming",
                    "source_kind": "streaming",
                    "title": "Exact Recording (1955)",
                    "description": "Glenn Gould Goldberg Variations 1955",
                    "platform": "youtube",
                    "weight": 0.9,
                    "same_recording_score": 0.94,
                    "fields": {},
                    "images": [],
                },
                {
                    "url": "https://stream.example/wrong-year",
                    "source_label": "Streaming",
                    "source_kind": "streaming",
                    "title": "Same work, wrong year (1981)",
                    "description": "Glenn Gould Goldberg Variations 1981",
                    "platform": "youtube",
                    "weight": 0.82,
                    "same_recording_score": 0.78,
                    "fields": {},
                    "images": [],
                },
            ]

        async def search_fallback(self, draft, profile):
            return []

    request = CreateJobRequest.model_validate(sample_request())
    pipeline = RetrievalPipeline(source_provider=MixedConfidenceSourceProvider(), llm_client=None)

    result = asyncio.run(pipeline.retrieve(request.items[0]))

    assert [link.url for link in result.result.links] == ["https://stream.example/right"]
    assert any(candidate.url == "https://stream.example/wrong-year" for candidate in result.link_candidates)


def test_pipeline_promotes_llm_accepted_candidate_into_final_result() -> None:
    class BorderlineSourceProvider:
        async def inspect_existing_links(self, draft, profile):
            return []

        async def search_high_quality(self, draft, profile):
            return []

        async def search_streaming(self, draft, profile):
            return [
                {
                    "url": "https://stream.example/borderline",
                    "source_label": "Streaming",
                    "source_kind": "streaming",
                    "title": "Kempe / LSO 1964",
                    "description": "Tchaikovsky Symphony No.5 Proms live",
                    "platform": "youtube",
                    "weight": 0.68,
                    "same_recording_score": 0.52,
                    "fields": {},
                    "images": [
                        {
                            "src": "https://stream.example/borderline.jpg",
                            "sourceUrl": "https://stream.example/borderline",
                            "sourceKind": "streaming",
                            "title": "Kempe / LSO 1964",
                        }
                    ],
                }
            ]

        async def search_fallback(self, draft, profile):
            return []

    class AcceptingLlm:
        async def synthesize(self, draft, profile, records):
            return {
                "summary": "LLM confirmed the borderline candidate as the same recording.",
                "acceptedUrls": ["https://stream.example/borderline"],
            }

    request = CreateJobRequest.model_validate(sample_request())
    pipeline = RetrievalPipeline(source_provider=BorderlineSourceProvider(), llm_client=AcceptingLlm())

    result = asyncio.run(pipeline.retrieve(request.items[0]))

    assert result.result.links
    assert result.result.links[0].url == "https://stream.example/borderline"
    assert result.result.images


def test_pipeline_keeps_multiple_equivalent_upload_links_when_llm_confirms_same_version() -> None:
    class MultiUploadSourceProvider:
        async def inspect_existing_links(self, draft, profile):
            return []

        async def search_high_quality(self, draft, profile):
            return []

        async def search_streaming(self, draft, profile):
            return [
                {
                    "url": "https://stream.example/upload-a",
                    "source_label": "Streaming",
                    "source_kind": "streaming",
                    "title": "Heifetz / Toscanini 1940",
                    "description": "Same recording upload A",
                    "platform": "youtube",
                    "weight": 0.72,
                    "same_recording_score": 0.6,
                    "fields": {},
                    "images": [],
                },
                {
                    "url": "https://stream.example/upload-b",
                    "source_label": "Streaming",
                    "source_kind": "streaming",
                    "title": "Heifetz / Toscanini 1940 new edition",
                    "description": "Same recording upload B",
                    "platform": "youtube",
                    "weight": 0.72,
                    "same_recording_score": 0.6,
                    "fields": {},
                    "images": [],
                },
                {
                    "url": "https://stream.example/upload-c",
                    "source_label": "Streaming",
                    "source_kind": "streaming",
                    "title": "Heifetz / Toscanini 1940 restored",
                    "description": "Same recording upload C",
                    "platform": "youtube",
                    "weight": 0.72,
                    "same_recording_score": 0.59,
                    "fields": {},
                    "images": [],
                },
            ]

        async def search_fallback(self, draft, profile):
            return []

    class MultiAcceptingLlm:
        async def synthesize(self, draft, profile, records):
            return {
                "summary": "These uploads point to the same historical recording.",
                "acceptedUrls": [
                    "https://stream.example/upload-a",
                    "https://stream.example/upload-b",
                    "https://stream.example/upload-c",
                ],
            }

    request = CreateJobRequest.model_validate(sample_request())
    pipeline = RetrievalPipeline(source_provider=MultiUploadSourceProvider(), llm_client=MultiAcceptingLlm())

    result = asyncio.run(pipeline.retrieve(request.items[0]))

    assert [link.url for link in result.result.links] == [
        "https://stream.example/upload-a",
        "https://stream.example/upload-b",
        "https://stream.example/upload-c",
    ]


def test_pipeline_promotes_clean_same_recording_upload_variant_into_final_links() -> None:
    class AmbiguousUploadSourceProvider:
        async def inspect_existing_links(self, draft, profile):
            return []

        async def search_high_quality(self, draft, profile):
            return []

        async def search_streaming(self, draft, profile):
            return [
                {
                    "url": "https://www.youtube.com/watch?v=XazjX-k2aco",
                    "source_label": "YouTube Search",
                    "source_kind": "streaming",
                    "title": "ベートーヴェン：ヴァイオリン協奏曲 ニ長調 作品61 ハイフェッツ, トスカニーニ 1940",
                    "description": "Jascha Heifetz violin Arturo Toscanini NBC Symphony Orchestra 11 March 1940",
                    "platform": "youtube",
                    "weight": 0.68,
                    "same_recording_score": 0.97,
                    "fields": {},
                    "images": [],
                },
                {
                    "url": "https://www.youtube.com/watch?v=8Aclk_O4bSc",
                    "source_label": "YouTube Search",
                    "source_kind": "streaming",
                    "title": "Beethoven: Violin Concerto (Heifetz/Toscanini 1940)",
                    "description": "Toscanini NBC Symphony Jascha Heifetz violin 11 Mar 1940",
                    "platform": "youtube",
                    "weight": 0.68,
                    "same_recording_score": 0.97,
                    "fields": {},
                    "images": [],
                },
                {
                    "url": "https://www.youtube.com/watch?v=IFBQqw_-W5A",
                    "source_label": "YouTube Search",
                    "source_kind": "streaming",
                    "title": "L. V. Beethoven, Violin Concerto - J. Heifetz (Vn) - A. Toscanini (C) - NBC Symphony Orch (1940)",
                    "description": "Full concerto upload with movements and 1940 date",
                    "platform": "youtube",
                    "weight": 0.68,
                    "same_recording_score": 0.97,
                    "fields": {},
                    "images": [],
                },
                {
                    "url": "https://www.youtube.com/watch?v=9YWr1UcbZE8",
                    "source_label": "YouTube Search",
                    "source_kind": "streaming",
                    "title": "Beethoven: Violin Concerto (1940) Heifetz/Toscanini",
                    "description": "Canonical upload title without edition tag",
                    "platform": "youtube",
                    "weight": 0.68,
                    "same_recording_score": 0.81,
                    "fields": {},
                    "images": [],
                },
                {
                    "url": "https://www.youtube.com/watch?v=-rUNkiGgJx8",
                    "source_label": "YouTube Search",
                    "source_kind": "streaming",
                    "title": "Beethoven: Violin Concerto (1940) Heifetz/Toscanini NEW EDITION",
                    "description": "Variant upload with edition tag",
                    "platform": "youtube",
                    "weight": 0.68,
                    "same_recording_score": 0.81,
                    "fields": {},
                    "images": [],
                },
            ]

        async def search_fallback(self, draft, profile):
            return []

    payload = sample_request()
    payload["items"][0]["workTypeHint"] = "concerto"
    payload["items"][0]["sourceLine"] = "Ludwig van Beethoven | Violin Concerto in D major, Op. 61 | Jascha Heifetz | Arturo Toscanini | March 11, 1940"
    payload["items"][0]["seed"]["title"] = "Heifetz / Toscanini 1940"
    payload["items"][0]["seed"]["composerNameLatin"] = "Ludwig van Beethoven"
    payload["items"][0]["seed"]["workTitleLatin"] = "Violin Concerto in D major, Op. 61"
    payload["items"][0]["seed"]["catalogue"] = "Op.61"
    payload["items"][0]["seed"]["performanceDateText"] = "March 11, 1940"
    payload["items"][0]["seed"]["credits"] = [
        {"role": "soloist", "displayName": "Jascha Heifetz", "label": "Jascha Heifetz"},
        {"role": "conductor", "displayName": "Arturo Toscanini", "label": "Arturo Toscanini"},
    ]
    request = CreateJobRequest.model_validate(payload)
    pipeline = RetrievalPipeline(source_provider=AmbiguousUploadSourceProvider(), llm_client=None)

    result = asyncio.run(pipeline.retrieve(request.items[0]))

    final_urls = [link.url for link in result.result.links]
    assert "https://www.youtube.com/watch?v=9YWr1UcbZE8" in final_urls
    assert "https://www.youtube.com/watch?v=-rUNkiGgJx8" not in final_urls


def test_pipeline_skips_llm_synthesis_for_unambiguous_top_candidate() -> None:
    class UnambiguousSourceProvider:
        async def inspect_existing_links(self, draft, profile):
            return []

        async def search_high_quality(self, draft, profile):
            return []

        async def search_streaming(self, draft, profile):
            return [
                {
                    "url": "https://stream.example/exact",
                    "source_label": "Streaming",
                    "source_kind": "streaming",
                    "title": "Exact Recording",
                    "description": "Exact same recording with matching performers and year.",
                    "platform": "youtube",
                    "weight": 0.95,
                    "same_recording_score": 0.93,
                    "fields": {"albumTitle": "Exact Recording"},
                    "images": [],
                },
                {
                    "url": "https://stream.example/distant-second",
                    "source_label": "Streaming",
                    "source_kind": "streaming",
                    "title": "Similar but lower confidence",
                    "description": "Same work, weaker evidence.",
                    "platform": "youtube",
                    "weight": 0.6,
                    "same_recording_score": 0.33,
                    "fields": {},
                    "images": [],
                },
            ]

        async def search_fallback(self, draft, profile):
            return []

    class CountingLlm:
        def __init__(self) -> None:
            self.calls = 0

        async def synthesize(self, draft, profile, records):
            self.calls += 1
            return {"summary": "should not be called"}

    request = CreateJobRequest.model_validate(sample_request())
    llm = CountingLlm()
    pipeline = RetrievalPipeline(source_provider=UnambiguousSourceProvider(), llm_client=llm)

    result = asyncio.run(pipeline.retrieve(request.items[0]))

    assert result.result.links
    assert result.result.links[0].url == "https://stream.example/exact"
    assert llm.calls == 0


def test_pipeline_isolates_access_events_between_concurrent_retrievals() -> None:
    class IsolatedAccessProvider(HttpSourceProvider):
        async def inspect_existing_links(self, draft, profile):
            del draft, profile
            return []

        async def search_high_quality(self, draft, profile):
            del profile
            self._record_access_event(
                url=f"https://catalog.example/{draft.item_id}",
                operation="test-search",
                ok=True,
                duration_ms=1.0,
                source_kind="high-quality",
                source_label=draft.item_id,
                query=draft.item_id,
            )
            return []

        async def search_streaming(self, draft, profile):
            del draft, profile
            return []

        async def search_fallback(self, draft, profile):
            del draft, profile
            return []

    async def run_test() -> tuple[list[dict], list[dict]]:
        payload = sample_request(item_count=2)
        payload["items"][0]["itemId"] = "item-a"
        payload["items"][0]["seed"]["title"] = "Title A"
        payload["items"][1]["itemId"] = "item-b"
        payload["items"][1]["seed"]["title"] = "Title B"
        request = CreateJobRequest.model_validate(payload)
        pipeline = RetrievalPipeline(source_provider=IsolatedAccessProvider(), llm_client=None)
        ready = asyncio.Event()
        completed = 0

        async def run_item(item):
            nonlocal completed
            await pipeline.retrieve(item)
            completed += 1
            if completed == 2:
                ready.set()
            await ready.wait()
            return pipeline.consume_access_events()

        return await asyncio.gather(*(run_item(item) for item in request.items))

    first_events, second_events = asyncio.run(run_test())

    assert [event["query"] for event in first_events] == ["item-a"]
    assert [event["query"] for event in second_events] == ["item-b"]


def test_pipeline_prefers_canonical_exact_upload_for_sparse_heifetz_query() -> None:
    class SparseHeifetzProvider:
        async def inspect_existing_links(self, draft, profile):
            del draft, profile
            return []

        async def search_high_quality(self, draft, profile):
            del draft, profile
            return []

        async def search_streaming(self, draft, profile):
            del draft, profile
            return [
                {
                    "url": "https://www.youtube.com/watch?v=XazjX-k2aco",
                    "source_label": "YouTube Search",
                    "source_kind": "streaming",
                    "title": "Beethoven Violin Concerto - Heifetz",
                    "description": "Historic upload",
                    "platform": "youtube",
                    "weight": 0.68,
                    "same_recording_score": 0.97,
                    "duration_seconds": 0,
                    "uploader": "",
                    "view_count": 180,
                    "fields": {},
                    "images": [],
                },
                {
                    "url": "https://www.youtube.com/watch?v=IFBQqw_-W5A",
                    "source_label": "YouTube Search",
                    "source_kind": "streaming",
                    "title": "L. V. Beethoven, Violin Concerto, Op. 61 - J. Heifetz - NBC Symphony Orch. (1940)",
                    "description": "Complete concerto upload",
                    "platform": "youtube",
                    "weight": 0.68,
                    "same_recording_score": 0.9,
                    "duration_seconds": 2610,
                    "uploader": "Historic Vault",
                    "view_count": 14500,
                    "fields": {},
                    "images": [],
                },
                {
                    "url": "https://www.youtube.com/watch?v=9YWr1UcbZE8",
                    "source_label": "YouTube Search",
                    "source_kind": "streaming",
                    "title": "Beethoven: Violin Concerto, Op.61 - Heifetz / Toscanini",
                    "description": "Canonical upload title",
                    "platform": "youtube",
                    "weight": 0.68,
                    "same_recording_score": 0.81,
                    "duration_seconds": 2664,
                    "uploader": "Classical Archive",
                    "view_count": 32200,
                    "fields": {},
                    "images": [],
                },
            ]

        async def search_fallback(self, draft, profile):
            del draft, profile
            return []

    payload = sample_request()
    payload["items"][0]["workTypeHint"] = "concerto"
    payload["items"][0]["sourceLine"] = "Ludwig van Beethoven | Violin Concerto in D major, Op. 61 | Jascha Heifetz | - | -"
    payload["items"][0]["seed"]["title"] = "Heifetz"
    payload["items"][0]["seed"]["composerNameLatin"] = "Ludwig van Beethoven"
    payload["items"][0]["seed"]["workTitleLatin"] = "Violin Concerto in D major, Op. 61"
    payload["items"][0]["seed"]["catalogue"] = "Op.61"
    payload["items"][0]["seed"]["performanceDateText"] = ""
    payload["items"][0]["seed"]["credits"] = [
        {"role": "soloist", "displayName": "Jascha Heifetz", "label": "Jascha Heifetz"},
    ]
    request = CreateJobRequest.model_validate(payload)
    pipeline = RetrievalPipeline(source_provider=SparseHeifetzProvider(), llm_client=None)

    result = asyncio.run(pipeline.retrieve(request.items[0]))

    final_urls = [link.url for link in result.result.links]
    assert final_urls[0] == "https://www.youtube.com/watch?v=9YWr1UcbZE8"
    assert "https://www.youtube.com/watch?v=9YWr1UcbZE8" in final_urls
    assert "https://www.youtube.com/watch?v=XazjX-k2aco" not in final_urls


def test_pipeline_aclose_closes_source_provider() -> None:
    provider = ClosableSourceProvider()
    pipeline = RetrievalPipeline(source_provider=provider, llm_client=None)

    asyncio.run(pipeline.aclose())

    assert provider.closed is True


def test_pipeline_keeps_exact_karajan_upload_among_close_year_matched_ties() -> None:
    class KarajanProvider:
        async def inspect_existing_links(self, draft, profile):
            del draft, profile
            return []

        async def search_high_quality(self, draft, profile):
            del draft, profile
            return []

        async def search_streaming(self, draft, profile):
            del draft, profile
            return [
                {
                    "url": "https://www.youtube.com/watch?v=iPQWH7rKlaM",
                    "source_label": "YouTube Search",
                    "source_kind": "streaming",
                    "title": "Richard Strauss - Eine Alpensinfonie / Karajan - Berliner Philharmoniker / Live Recording 1982",
                    "platform": "youtube",
                    "weight": 0.68,
                    "same_recording_score": 0.97,
                    "duration_seconds": 3060,
                    "uploader": "Vault",
                    "view_count": 21000,
                    "fields": {},
                    "images": [],
                    "description": "",
                },
                {
                    "url": "https://www.bilibili.com/video/BV1WV4y1h799/",
                    "source_label": "Bilibili Search",
                    "source_kind": "streaming",
                    "title": "卡拉扬《理查·施特劳斯：阿尔卑斯山交响曲》柏林爱乐「BD」_哔哩哔哩_bilibili",
                    "platform": "bilibili",
                    "weight": 0.68,
                    "same_recording_score": 0.97,
                    "duration_seconds": 3050,
                    "uploader": "Uploader",
                    "view_count": 15000,
                    "fields": {},
                    "images": [],
                    "description": "",
                },
                {
                    "url": "https://www.youtube.com/watch?v=fDi1PSz8mRE",
                    "source_label": "YouTube Search",
                    "source_kind": "streaming",
                    "title": "STRAUSS: ALPINE SYMPHONY / BERLIN  PO / KARAJAN  (1982 live)",
                    "platform": "youtube",
                    "weight": 0.68,
                    "same_recording_score": 0.97,
                    "duration_seconds": 3058,
                    "uploader": "Archive",
                    "view_count": 18800,
                    "fields": {},
                    "images": [],
                    "description": "",
                },
                {
                    "url": "https://www.youtube.com/watch?v=oPpGxrUHLO4",
                    "source_label": "YouTube Search",
                    "source_kind": "streaming",
                    "title": "Richard Strauss – Eine Alpensinfonie – Herbert von Karajan, Berliner Philharmoniker, 1981",
                    "platform": "youtube",
                    "weight": 0.68,
                    "same_recording_score": 0.97,
                    "duration_seconds": 3042,
                    "uploader": "Archive",
                    "view_count": 17000,
                    "fields": {},
                    "images": [],
                    "description": "",
                },
            ]

        async def search_fallback(self, draft, profile):
            del draft, profile
            return []

    payload = sample_request()
    payload["items"][0]["workTypeHint"] = "orchestral"
    payload["items"][0]["sourceLine"] = "Richard Strauss | Eine Alpensinfonie, Op.64 | Herbert von Karajan | Berlin Philharmonic Orchestra | August 28, 1982 Salzburg"
    payload["items"][0]["seed"]["title"] = "Karajan Alpine 1982"
    payload["items"][0]["seed"]["composerName"] = "理查·施特劳斯"
    payload["items"][0]["seed"]["composerNameLatin"] = "Richard Strauss"
    payload["items"][0]["seed"]["workTitle"] = "阿尔卑斯山交响曲"
    payload["items"][0]["seed"]["workTitleLatin"] = "Eine Alpensinfonie, Op.64"
    payload["items"][0]["seed"]["catalogue"] = "Op.64"
    payload["items"][0]["seed"]["performanceDateText"] = "August 28, 1982 Salzburg"
    payload["items"][0]["seed"]["credits"] = [
        {"role": "conductor", "displayName": "Herbert von Karajan", "label": "Herbert von Karajan"},
        {"role": "orchestra", "displayName": "Berlin Philharmonic Orchestra", "label": "Berlin Philharmonic Orchestra"},
    ]
    request = CreateJobRequest.model_validate(payload)
    pipeline = RetrievalPipeline(source_provider=KarajanProvider(), llm_client=None)

    result = asyncio.run(pipeline.retrieve(request.items[0]))

    final_urls = [link.url for link in result.result.links]
    assert "https://www.youtube.com/watch?v=fDi1PSz8mRE" in final_urls
    assert "https://www.youtube.com/watch?v=oPpGxrUHLO4" not in final_urls
