from __future__ import annotations

from pathlib import Path

from app.models.protocol import CreateJobRequest
from app.services.pipeline import ProfileResolver
from app.services.source_profiles import OrchestraAliasLoader, PersonAliasLoader, SourceProfileLoader
from tests.fixtures import sample_request


def write_profile(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content.strip() + "\n", encoding="utf-8")


def test_source_profile_loader_reads_single_file_sections(tmp_path: Path) -> None:
    root = tmp_path / "source-profiles"
    write_profile(
        root / "high-quality.txt",
        """
        #global
        https://global.example
        hq-global.example
        #orchestral
        https://orchestral.example
        hq-global.example
        #piano
        https://piano.example
        """,
    )
    write_profile(
        root / "streaming.txt",
        """
        #global
        https://youtube.example
        #orchestral
        https://bilibili.example
        #live
        https://concert.example
        """,
    )

    loader = SourceProfileLoader(root)
    merged = loader.load(category="orchestral", tags=["piano", "live"])

    assert [entry.url for entry in merged.high_quality] == [
        "https://global.example",
        "hq-global.example",
        "https://orchestral.example",
        "https://piano.example",
    ]
    assert [entry.url for entry in merged.streaming] == [
        "https://youtube.example",
        "https://bilibili.example",
        "https://concert.example",
    ]


def test_source_profile_loader_reads_platform_language_annotations(tmp_path: Path) -> None:
    root = tmp_path / "source-profiles"
    write_profile(
        root / "streaming.txt",
        """
        #global
        [zh] https://www.bilibili.com
        https://www.youtube.com
        """,
    )
    write_profile(root / "high-quality.txt", "#global\nhttps://catalog.example\n")

    loader = SourceProfileLoader(root)
    merged = loader.load(category="orchestral", tags=[])

    assert merged.streaming[0].url == "https://www.bilibili.com"
    assert merged.streaming[0].is_chinese is True
    assert merged.streaming[1].url == "https://www.youtube.com"
    assert merged.streaming[1].is_chinese is False


def test_orchestra_alias_loader_resolves_abbreviation_and_full_name(tmp_path: Path) -> None:
    path = tmp_path / "orchestra-abbreviations.txt"
    path.write_text(
        "\n".join(
            [
                "LSO = London Symphony Orchestra",
                "BSO = Boston Symphony Orchestra",
            ]
        ),
        encoding="utf-8",
    )

    loader = OrchestraAliasLoader(path)

    assert loader.expand("LSO") == ["LSO", "London Symphony Orchestra"]
    assert loader.expand("London Symphony Orchestra") == ["London Symphony Orchestra", "LSO"]


def test_person_alias_loader_expands_both_directions_and_persists_memory(tmp_path: Path) -> None:
    path = tmp_path / "person-name-aliases.txt"
    path.write_text(
        "\n".join(
            [
                "#global",
                "西贝柳斯 = 西贝留士 = Sibelius = Jean Sibelius",
                "#conductor",
                "蒙都 = Monteux = Pierre Monteux",
            ]
        ),
        encoding="utf-8",
    )

    loader = PersonAliasLoader(path)
    assert loader.expand("蒙都", role="conductor") == ["蒙都", "Monteux", "Pierre Monteux"]
    assert loader.expand("Monteux", role="conductor")[0] == "Monteux"
    assert "蒙都" in loader.expand("Monteux", role="conductor")

    loader.remember(role="soloist", values=["安妮·费舍尔", "Annie Fischer"])

    reloaded = PersonAliasLoader(path)
    assert reloaded.expand("安妮·费舍尔", role="soloist") == ["安妮·费舍尔", "Annie Fischer"]


def test_profile_resolver_adds_live_and_piano_tags() -> None:
    payload = sample_request()
    payload["items"][0]["workTypeHint"] = "chamber_solo"
    payload["items"][0]["seed"]["title"] = "Argerich 1982 Live"
    payload["items"][0]["seed"]["workTitle"] = "Piano Sonata No. 2"
    payload["items"][0]["sourceLine"] = "Argerich | 1982 | live in Lugano"
    request = CreateJobRequest.model_validate(payload)

    profile = ProfileResolver().resolve(request.items[0])

    assert profile.category == "chamber_solo"
    assert "piano" in profile.tags
    assert "live" in profile.tags
    assert any("Argerich" in query for query in profile.queries)
