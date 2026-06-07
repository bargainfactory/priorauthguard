"""WebSocket voice-stream tests."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from pa_guard.api.main import app


@pytest.fixture(scope="module")
def client() -> TestClient:
    with TestClient(app) as c:
        yield c


def test_chunk_returns_deidentified_text(client: TestClient) -> None:
    with client.websocket_connect("/v1/voice/stream") as ws:
        ws.send_json(
            {
                "type": "chunk",
                "text": "Mr. John Smith MRN: AB12345678 follow-up visit.",
                "speaker_role": "provider",
            }
        )
        msg = ws.receive_json()
        assert msg["type"] == "deidentified"
        assert "Smith" not in msg["text"]
        assert "AB12345678" not in msg["text"]
        assert msg["identifiers_redacted"] >= 2

        ws.send_json({"type": "end"})
        summary = ws.receive_json()
        assert summary["type"] == "summary"
        assert summary["total_chunks"] == 1
        assert summary["total_identifiers_redacted"] >= 2


def test_flush_acks_and_processes_text(client: TestClient) -> None:
    with client.websocket_connect("/v1/voice/stream") as ws:
        ws.send_json({"type": "flush", "text": "Patient MRN: XYZ999."})
        ack = ws.receive_json()
        assert ack["type"] == "ack"
        de = ws.receive_json()
        assert de["type"] == "deidentified"


def test_unknown_type_emits_error(client: TestClient) -> None:
    with client.websocket_connect("/v1/voice/stream") as ws:
        ws.send_json({"type": "ping"})
        err = ws.receive_json()
        assert err["type"] == "error"
