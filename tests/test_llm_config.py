from __future__ import annotations

import asyncio
import json
from pathlib import Path

from app.services.llm_client import DualModelLlmClient, ModelConfig, OpenAiCompatibleLlmClient, load_llm_config, migrate_legacy_llm_config


def test_load_llm_config_reads_dual_model_shape(tmp_path: Path) -> None:
    config_path = tmp_path / "llm.local.json"
    config_path.write_text(
        json.dumps(
            {
                "enabled": True,
                "fastModel": {
                    "enabled": True,
                    "baseUrl": "https://fast.example/v1",
                    "apiKey": "fast-secret",
                    "model": "deepseek-chat",
                    "timeoutMs": 12000,
                },
                "reasoningModel": {
                    "enabled": True,
                    "baseUrl": "https://reason.example/v1",
                    "apiKey": "reason-secret",
                    "model": "deepseek-reasoner",
                    "timeoutMs": 30000,
                },
            }
        ),
        encoding="utf-8",
    )

    config = load_llm_config(config_path)

    assert config.fast.model == "deepseek-chat"
    assert config.fast.base_url == "https://fast.example/v1"
    assert config.reasoning.model == "deepseek-reasoner"
    assert config.reasoning.base_url == "https://reason.example/v1"


def test_migrate_legacy_llm_config_reads_two_entries_and_persists_dual_models(tmp_path: Path) -> None:
    legacy_path = tmp_path / "LLM config.txt"
    legacy_path.write_text(
        "\n".join(
            [
                "key1:",
                "https://api.deepseek.com/v1",
                "sk-reason",
                "deepseek-reasoner",
                "key2:",
                "https://api.deepseek.com/v1",
                "sk-fast",
                "deepseek-chat",
            ]
        ),
        encoding="utf-8",
    )
    runtime_path = tmp_path / "llm.local.json"

    migrated = migrate_legacy_llm_config(legacy_path=legacy_path, runtime_path=runtime_path)
    assert migrated is True

    config = load_llm_config(runtime_path)
    assert config.reasoning.model == "deepseek-reasoner"
    assert config.reasoning.api_key == "sk-reason"
    assert config.fast.model == "deepseek-chat"
    assert config.fast.api_key == "sk-fast"

def test_dual_model_client_flags_realtime_capabilities_based_on_fast_model(tmp_path: Path) -> None:
    payload = {
        "enabled": True,
        "fastModel": {
            "enabled": True,
            "baseUrl": "https://fast.example/v1",
            "apiKey": "fast-secret",
            "model": "deepseek-chat",
            "timeoutMs": 12000,
        },
        "reasoningModel": {
            "enabled": True,
            "baseUrl": "https://reason.example/v1",
            "apiKey": "reason-secret",
            "model": "deepseek-reasoner",
            "timeoutMs": 30000,
        },
    }

    client = DualModelLlmClient(load_llm_config_from_payload(payload, tmp_path))

    assert client.allow_realtime_analysis is True
    assert client.allow_realtime_synthesis is True
    assert client.minimum_synthesis_timeout_seconds == 4.0


def test_openai_compatible_client_recreates_underlying_client_when_event_loop_changes() -> None:
    created_clients: list[LoopBoundFakeClient] = []

    def factory() -> LoopBoundFakeClient:
        client = LoopBoundFakeClient()
        created_clients.append(client)
        return client

    client = OpenAiCompatibleLlmClient(
        ModelConfig(
            enabled=True,
            base_url="https://llm.example/v1",
            api_key="secret",
            model="deepseek-chat",
            timeout_ms=12000,
        ),
        client_factory=factory,
    )

    async def run_once() -> dict:
        return await client._chat_json(
            [
                {"role": "system", "content": "Return strict JSON only."},
                {"role": "user", "content": "{}"},
            ]
        )

    first = asyncio.run(run_once())
    second = asyncio.run(run_once())

    assert first == {}
    assert second == {}
    assert len(created_clients) == 2


class LoopBoundFakeClient:
    def __init__(self) -> None:
        self._loop: asyncio.AbstractEventLoop | None = None

    async def post(self, *args, **kwargs) -> "_FakeResponse":
        del args, kwargs
        current_loop = asyncio.get_running_loop()
        if self._loop is None:
            self._loop = current_loop
        elif self._loop is not current_loop:
            raise RuntimeError("Event loop is closed")
        return _FakeResponse()


class _FakeResponse:
    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict:
        return {"choices": [{"message": {"content": "{}"}}]}


def load_llm_config_from_payload(payload: dict, tmp_path: Path) -> object:
    path = tmp_path / ".llm-config-test.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return load_llm_config(path)
