"""Cloud voice adapters: Deepgram (STT), ElevenLabs (TTS), Twilio (telephony).

Each adapter is **lazy**: it never imports its SDK at module load time, and it
refuses to construct unless its API key is present in settings. This keeps the
core install lean and prevents accidental cloud use in dev/test.

The Phase 1 implementations follow each vendor's documented streaming surface
without performing real network calls in tests — instead, `VoiceService` keeps
the offline stubs as the default. Production deployments switch to these by
setting `PAG_VOICE_CLOUD_ENABLED=true` and providing the corresponding API
key env vars.
"""
from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import UTC, datetime

from ..core.config import Settings, get_settings
from ..core.logging import get_logger
from ..core.models import VoiceChannel, VoiceTranscriptChunk

# ---------------------------------------------------------------------------
# Deepgram STT
# ---------------------------------------------------------------------------

@dataclass
class DeepgramAdapter:
    """Deepgram streaming STT adapter.

    Wraps `deepgram-sdk` v3+. The SDK is imported lazily so the dependency
    only matters when this adapter is actually used.
    """

    channel: VoiceChannel = VoiceChannel.CLOUD_DEEPGRAM
    on_device: bool = False
    settings: Settings | None = None

    def __post_init__(self) -> None:
        s = self.settings or get_settings()
        if not s.deepgram_api_key:
            raise RuntimeError(
                "DeepgramAdapter requires PAG_DEEPGRAM_API_KEY to be set."
            )
        self._api_key = s.deepgram_api_key
        self._log = get_logger("DeepgramAdapter")

    async def stream(
        self, audio_chunks: AsyncIterator[bytes], *, speaker_role: str
    ) -> AsyncIterator[VoiceTranscriptChunk]:
        try:
            from deepgram import (
                DeepgramClient,
                LiveOptions,
                LiveTranscriptionEvents,
            )
        except ImportError as e:  # pragma: no cover — install-time guard
            raise RuntimeError(
                "deepgram-sdk is required for DeepgramAdapter; "
                "install with `pip install deepgram-sdk`."
            ) from e

        client = DeepgramClient(self._api_key)
        connection = client.listen.asyncwebsocket.v("1")
        results: list[VoiceTranscriptChunk] = []

        async def _on_message(_self, result, **_kwargs):  # type: ignore[no-untyped-def]
            text = result.channel.alternatives[0].transcript
            if not text:
                return
            now = datetime.now(UTC)
            results.append(
                VoiceTranscriptChunk(
                    channel=self.channel,
                    speaker_role=speaker_role,  # type: ignore[arg-type]
                    text=text,
                    started_at=now,
                    ended_at=now,
                    on_device=False,
                )
            )

        connection.on(LiveTranscriptionEvents.Transcript, _on_message)
        options = LiveOptions(model="nova-2-medical", punctuate=True, smart_format=True)
        await connection.start(options)
        try:
            async for chunk in audio_chunks:
                await connection.send(chunk)
                while results:
                    yield results.pop(0)
        finally:
            await connection.finish()
            while results:
                yield results.pop(0)


# ---------------------------------------------------------------------------
# ElevenLabs TTS
# ---------------------------------------------------------------------------

@dataclass
class ElevenLabsAdapter:
    """ElevenLabs streaming TTS adapter."""

    settings: Settings | None = None
    default_voice_id: str = "EXAVITQu4vr4xnSDxMaL"

    def __post_init__(self) -> None:
        s = self.settings or get_settings()
        if not s.elevenlabs_api_key:
            raise RuntimeError(
                "ElevenLabsAdapter requires PAG_ELEVENLABS_API_KEY to be set."
            )
        self._api_key = s.elevenlabs_api_key
        self._log = get_logger("ElevenLabsAdapter")

    async def synthesize(self, text: str, *, voice_id: str | None = None) -> bytes:
        try:
            from elevenlabs.client import AsyncElevenLabs
        except ImportError as e:  # pragma: no cover
            raise RuntimeError(
                "elevenlabs is required for ElevenLabsAdapter; "
                "install with `pip install elevenlabs`."
            ) from e

        client = AsyncElevenLabs(api_key=self._api_key)
        audio = b""
        stream = client.text_to_speech.convert(
            voice_id=voice_id or self.default_voice_id,
            text=text,
            model_id="eleven_turbo_v2_5",
        )
        async for chunk in stream:
            audio += chunk
        return audio


# ---------------------------------------------------------------------------
# Twilio outbound telephony
# ---------------------------------------------------------------------------

@dataclass
class TwilioAdapter:
    channel: VoiceChannel = VoiceChannel.CLOUD_TWILIO
    settings: Settings | None = None

    def __post_init__(self) -> None:
        s = self.settings or get_settings()
        if not (s.twilio_account_sid and s.twilio_auth_token):
            raise RuntimeError(
                "TwilioAdapter requires PAG_TWILIO_ACCOUNT_SID and "
                "PAG_TWILIO_AUTH_TOKEN to be set."
            )
        self._sid = s.twilio_account_sid
        self._token = s.twilio_auth_token
        self._log = get_logger("TwilioAdapter")

    async def place_call(self, *, to_number: str, script_prompt: str) -> str:
        try:
            from twilio.rest import Client
        except ImportError as e:  # pragma: no cover
            raise RuntimeError(
                "twilio is required for TwilioAdapter; "
                "install with `pip install twilio`."
            ) from e

        # Twilio's REST client is synchronous; we keep this thin and rely on
        # FastAPI's thread pool for the single network call.
        client = Client(self._sid, self._token)
        twiml = f"<Response><Say>{_xml_escape(script_prompt)}</Say></Response>"
        call = client.calls.create(
            to=to_number,
            from_=to_number,  # caller-ID provisioning must be configured in Twilio
            twiml=twiml,
        )
        self._log.info("twilio_call_placed", sid=call.sid)
        return str(call.sid)

    async def stream_audio(self, call_id: str) -> AsyncIterator[bytes]:
        # Real-time call media requires a Twilio Media Streams websocket; that
        # path is wired in Phase 5. For Phase 1 we surface a typed empty stream
        # so callers can compose without a special case.
        if False:  # pragma: no cover
            yield b""


def _xml_escape(s: str) -> str:
    return (
        s.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
        .replace("'", "&apos;")
    )


__all__ = ["DeepgramAdapter", "ElevenLabsAdapter", "TwilioAdapter"]
