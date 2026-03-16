from __future__ import annotations

from fastapi.testclient import TestClient

from app.main import create_app


def test_index_page_serves_standalone_ui() -> None:
    client = TestClient(create_app())

    response = client.get("/")

    assert response.status_code == 200
    assert "Recording Retrieval Service" in response.text
    assert "request-preview" in response.text


def test_static_asset_is_served() -> None:
    client = TestClient(create_app())

    response = client.get("/assets/app.js")

    assert response.status_code == 200
    assert "buildRequestPayload" in response.text
