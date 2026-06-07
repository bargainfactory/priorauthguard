"""Hybrid voice service: on-device Whisper + cloud (Deepgram / ElevenLabs / Twilio).

Design principles
-----------------
* **On-device first**: any audio captured from a clinician's device is
  transcribed locally via a quantized Whisper model (faster-whisper or
  whisper.cpp). Raw audio NEVER leaves the device.
* **Cloud only when justified**: outbound payer calls use a cloud STT/TTS
  stack under a signed BAA. Even there, transcripts are de-identified at the
  edge before any persistence.
* **Streaming-first**: STT methods are async generators that yield
  `VoiceTranscriptChunk`s, so the orchestrator can pipe them straight into
  `PrivacyGuardianAgent` chunk-by-chunk.

Phase 0 ships interfaces + offline stubs so the platform can be tested end-to-end
without provisioning Deepgram/ElevenLabs/Twilio. Phase 1 swaps the stubs with
real SDK calls.
"""
from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol

from ..core.config import Settings, get_settings
from ..core.logging import get_logger
from ..core.models import VoiceChannel, VoiceTranscriptChunk

# ---------------------------------------------------------------------------
# Adapter protocols
# ---------------------------------------------------------------------------

class SttBackend(Protocol):
    """Speech-to-text backend (one per channel)."""

    channel: VoiceChannel
    on_device: bool

    async def stream(
        self, audio_chunks: AsyncIterator[bytes], *, speaker_role: str
    ) -> AsyncIterator[VoiceTranscriptChunk]: ...


class TtsBackend(Protocol):
    """Text-to-speech backend (cloud-only — we don't run TTS on-device today)."""

    async def synthesize(self, text: str, *, voice_id: str | None = None) -> bytes: ...


class TelephonyBackend(Protocol):
    """Outbound voice channel (Twilio / Vapi / Bland / Retell)."""

    channel: VoiceChannel

    async def place_call(
        self, *, to_number: str, script_prompt: str
    ) -> str:
        """Returns an opaque call_id."""
        ...

    async def stream_audio(self, call_id: str) -> AsyncIterator[bytes]: ...


# ---------------------------------------------------------------------------
# Phase 0 offline stubs (deterministic for tests)
# ---------------------------------------------------------------------------

@dataclass
class _OnDeviceWhisperStub:
    channel: VoiceChannel = VoiceChannel.ON_DEVICE_WHISPER
    on_device: bool = True
    model: str = "small.en-q8"

    async def stream(
        self, audio_chunks: AsyncIterator[bytes], *, speaker_role: str
    ) -> AsyncIterator[VoiceTranscriptChunk]:
        # Without real Whisper, we surface the byte-length as a deterministic
        # placeholder so the orchestrator can be wired end-to-end.
        async for chunk in audio_chunks:
            now = datetime.now(UTC)
            yield VoiceTranscriptChunk(
                channel=self.channel,
                speaker_role=speaker_role,  # type: ignore[arg-type]
                text=f"<on-device whisper stub: {len(chunk)} bytes of audio>",
                started_at=now,
                ended_at=now,
                on_device=True,
            )


@dataclass
class _DeepgramStub:
    channel: VoiceChannel = VoiceChannel.CLOUD_DEEPGRAM
    on_device: bool = False

    async def stream(
        self, audio_chunks: AsyncIterator[bytes], *, speaker_role: str
    ) -> AsyncIterator[VoiceTranscriptChunk]:
        async for chunk in audio_chunks:
            now = datetime.now(UTC)
            yield VoiceTranscriptChunk(
                channel=self.channel,
                speaker_role=speaker_role,  # type: ignore[arg-type]
                text=f"<deepgram stub: {len(chunk)} bytes of audio>",
                started_at=now,
                ended_at=now,
                on_device=False,
            )


@dataclass
class _ElevenLabsStub:
    voice_id: str = "default"

    async def synthesize(self, text: str, *, voice_id: str | None = None) -> bytes:
        # Returns a tiny deterministic blob so contracts can be exercised.
        await asyncio.sleep(0)
        return f"<tts:{voice_id or self.voice_id}:{len(text)}>".encode()


@dataclass
class _TwilioStub:
    channel: VoiceChannel = VoiceChannel.CLOUD_TWILIO

    async def place_call(self, *, to_number: str, script_prompt: str) -> str:
        await asyncio.sleep(0)
        return f"call_stub_{abs(hash((to_number, script_prompt))) % (10**12):012d}"

    async def stream_audio(self, call_id: str) -> AsyncIterator[bytes]:
        # Yields nothing in Phase 0; Phase 1 wires the real Twilio media stream.
        if False:  # pragma: no cover
            yield b""


# ---------------------------------------------------------------------------
# Service
# ---------------------------------------------------------------------------

class VoiceService:
    """Hybrid voice service.

    Pick `transcribe_on_device(...)` for clinician dictation and
    `transcribe_cloud(...)` for inbound/outbound payer audio. Both return
    de-identification-pending `VoiceTranscriptChunk`s — the caller
    (`VoiceOrchestratorAgent`) routes each chunk through `PrivacyGuardianAgent`
    before persistence.
    """

    def __init__(
        self,
        settings: Settings | None = None,
        *,
        on_device_stt: SttBackend | None = None,
        cloud_stt: SttBackend | None = None,
        tts: TtsBackend | None = None,
        telephony: TelephonyBackend | None = None,
    ) -> None:
        self._settings = settings or get_settings()
        self._log = get_logger("VoiceService")
        self._on_device_stt = on_device_stt or _OnDeviceWhisperStub(
            model=self._settings.whisper_model
        )
        self._cloud_stt = cloud_stt or _DeepgramStub()
        self._tts = tts or _ElevenLabsStub()
        self._telephony = telephony or _TwilioStub()

    # ------------------------------------------------------------------
    # STT
    # ------------------------------------------------------------------

    async def transcribe_on_device(
        self,
        audio_chunks: AsyncIterator[bytes],
        *,
        speaker_role: str = "provider",
    ) -> AsyncIterator[VoiceTranscriptChunk]:
        if not self._settings.voice_on_device_enabled:
            raise RuntimeError("On-device voice is disabled in settings.")
        async for tx in self._on_device_stt.stream(
            audio_chunks, speaker_role=speaker_role
        ):
            yield tx

    async def transcribe_cloud(
        self,
        audio_chunks: AsyncIterator[bytes],
        *,
        speaker_role: str = "payer-agent",
    ) -> AsyncIterator[VoiceTranscriptChunk]:
        if not self._settings.voice_cloud_enabled:
            raise RuntimeError(
                "Cloud voice path is disabled in settings — outbound payer "
                "calls require explicit opt-in plus a signed BAA."
            )
        async for tx in self._cloud_stt.stream(
            audio_chunks, speaker_role=speaker_role
        ):
            yield tx

    # ------------------------------------------------------------------
    # TTS
    # ------------------------------------------------------------------

    async def synthesize(self, text: str, *, voice_id: str | None = None) -> bytes:
        return await self._tts.synthesize(text, voice_id=voice_id)

    # ------------------------------------------------------------------
    # Telephony
    # ------------------------------------------------------------------

    async def place_outbound_call(
        self, *, to_number: str, script_prompt: str
    ) -> str:
        if not self._settings.voice_cloud_enabled:
            raise RuntimeError("Outbound calls require voice_cloud_enabled=True.")
        return await self._telephony.place_call(
            to_number=to_number, script_prompt=script_prompt
        )

    async def stream_call_audio(self, call_id: str) -> AsyncIterator[bytes]:
        async for chunk in self._telephony.stream_audio(call_id):
            yield chunk


__all__ = ["SttBackend", "TelephonyBackend", "TtsBackend", "VoiceService"]
