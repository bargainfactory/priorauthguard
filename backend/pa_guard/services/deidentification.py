"""Thin de-identification service that the privacy agent consumes.

Wraps `SafeHarborEngine` behind an async, swappable interface so we can layer
a learned NER pass (Phase 2) or per-jurisdiction overlays without touching
the agent.
"""
from __future__ import annotations

from secrets import token_hex
from typing import Protocol

from ..compliance.safe_harbor import SafeHarborEngine
from ..core.models import (
    DeidentificationReport,
    PatientPseudoId,
    RawClinicalNote,
    SafeClinicalContext,
)


class DeidentificationService(Protocol):
    """Protocol so tests / Phase 2 can swap in an NER-augmented version."""

    async def deidentify(
        self,
        note: RawClinicalNote,
        *,
        pseudo_id: PatientPseudoId | None = None,
    ) -> tuple[DeidentificationReport, SafeClinicalContext]: ...


class SafeHarborService:
    """Default deterministic Safe Harbor service."""

    def __init__(self, engine: SafeHarborEngine | None = None) -> None:
        self._engine = engine or SafeHarborEngine()

    async def deidentify(
        self,
        note: RawClinicalNote,
        *,
        pseudo_id: PatientPseudoId | None = None,
    ) -> tuple[DeidentificationReport, SafeClinicalContext]:
        pid = pseudo_id or _new_pseudo_id()
        return self._engine.deidentify_note(note, pseudo_id=pid)


def _new_pseudo_id() -> PatientPseudoId:
    # 16 hex chars = 64 bits of entropy; collision-free for any realistic load.
    return f"pid_{token_hex(8)}"


__all__ = ["DeidentificationService", "SafeHarborService"]
