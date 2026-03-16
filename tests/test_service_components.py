from __future__ import annotations

import asyncio

from app.models.protocol import CreateJobRequest
from app.services.orchestrator import JobOrchestrator
from app.services.retrieval import StubRetriever
from tests.fixtures import sample_request


def test_stub_retriever_returns_contract_safe_payload() -> None:
    retriever = StubRetriever()
    request = CreateJobRequest.model_validate(sample_request())

    result = asyncio.run(retriever.retrieve(request.items[0]))

    assert result.status in {"succeeded", "partial", "not_found"}
    assert result.item_id == "recording-1"
    assert 0 <= result.confidence <= 1
    assert isinstance(result.result.model_dump(by_alias=True), dict)


def test_orchestrator_completes_job_and_isolates_item_results() -> None:
    orchestrator = JobOrchestrator(log_dir=None)
    request = CreateJobRequest.model_validate(sample_request(item_count=2))

    accepted = orchestrator.create_job(request)

    asyncio.run(orchestrator.wait_for_job(accepted.job_id, timeout=5))
    results = orchestrator.get_results(accepted.job_id)

    assert results is not None
    assert len(results.items) == 2
    assert {item.item_id for item in results.items} == {"recording-1", "recording-2"}


def test_orchestrator_marks_timeout() -> None:
    orchestrator = JobOrchestrator(log_dir=None, retriever=StubRetriever(delay_seconds=0.05))
    payload = sample_request(item_count=1)
    payload["options"]["timeoutMs"] = 1
    request = CreateJobRequest.model_validate(payload)

    accepted = orchestrator.create_job(request)
    asyncio.run(orchestrator.wait_for_job(accepted.job_id, timeout=5))
    status = orchestrator.get_status(accepted.job_id)

    assert status is not None
    assert status.status == "timed_out"
