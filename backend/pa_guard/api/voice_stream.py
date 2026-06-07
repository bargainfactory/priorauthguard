"""WebSocket streaming voice surface.

Wire protocol
-------------
Client → server messages (JSON text frames):

    {"type": "chunk",   "text": "<verbatim STT chunk>", "speaker_role": "provider"}
    {"type": "flush",   "text": "<verbatim STT chunk>", "speaker_role": "provider"}
    {"type": "end"}

Server → client messages:

    {"type": "deidentified",
     "chunk_id":  "<uuid>",
     "text":      "<safe-harbor cleaned chunk>",
     "identifiers_redacted": <int>}
    {"type": "ack", "kind": "flush"}
    {"type": "summary",
     "total_chunks": <int>,
     "total_identifiers_redacted": <int>}

The server **never** persists or echoes the raw text — only the cleaned
version is sent back, and the raw chunk is dropped before the next frame is
read. The client is the only place the raw text exists.
"""
from __future__ import annotations

import json
from datetime import UTC, datetime

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from ..agents.privacy_guardian import PrivacyGuardianAgent
from ..core.logging import get_logger
from ..core.models import VoiceChannel, VoiceTranscriptChunk

router = APIRouter()


@router.websocket("/v1/voice/stream")
async def voice_stream(websocket: WebSocket) -> None:
    log = get_logger("voice_stream")
    await websocket.accept()
    guardian: PrivacyGuardianAgent = websocket.app.state.privacy_guardian

    total_chunks = 0
    total_redactions = 0

    try:
        while True:
            raw = await websocket.receive_text()
            try:
                msg = json.loads(raw)
            except json.JSONDecodeError:
                await websocket.send_json({"type": "error", "message": "invalid json"})
                continue

            kind = msg.get("type")
            if kind == "end":
                await websocket.send_json(
                    {
                        "type": "summary",
                        "total_chunks": total_chunks,
                        "total_identifiers_redacted": total_redactions,
                    }
                )
                await websocket.close()
                return

            if kind == "flush":
                await websocket.send_json({"type": "ack", "kind": "flush"})
                # Some clients use flush to signal a sentence boundary without
                # sending new text; if text is present, still de-identify it.
                if not msg.get("text"):
                    continue

            if kind not in {"chunk", "flush"}:
                await websocket.send_json(
                    {"type": "error", "message": f"unknown type {kind!r}"}
                )
                continue

            text = str(msg.get("text", ""))
            if not text.strip():
                continue

            now = datetime.now(UTC)
            chunk = VoiceTranscriptChunk(
                channel=VoiceChannel.ON_DEVICE_WHISPER,
                speaker_role=msg.get("speaker_role", "provider"),
                text=text,
                started_at=now,
                ended_at=now,
                on_device=True,
            )
            result = await guardian.deidentify_transcript(chunk)
            redacted = sum(result.deid_report.identifier_counts.values())
            total_chunks += 1
            total_redactions += redacted

            await websocket.send_json(
                {
                    "type": "deidentified",
                    "chunk_id": str(result.chunk_id),
                    "text": result.cleaned_text,
                    "identifiers_redacted": redacted,
                }
            )
    except WebSocketDisconnect:
        log.info("voice_stream_disconnected", chunks=total_chunks)
    except Exception as exc:
        log.error("voice_stream_error", error=str(exc))
        try:
            await websocket.send_json({"type": "error", "message": str(exc)})
        finally:
            await websocket.close()


__all__ = ["router"]
