"""Thin de-identification service that the privacy agent consumes.

Wraps `SafeHarborEngine` behind an async, swappable interface so we can layer
a learned NER pass (Phase 2) or per-jurisdiction overlays without touching
the agent.
"""
from __future__ import annotations

from secrets import token_hex
from typing import Protocol

from ..compliance.ner_overlay import NerDeidOverlay
from ..compliance.safe_harbor import SafeHarborEngine, SafeHarborIdentifier
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
    """Default Safe Harbor service.

    Runs the deterministic engine first (Phase 0) then, when an `NerDeidOverlay`
    is attached (Phase 1+), adds learned NAME redactions for the long tail.
    The overlay's count of additional redactions is folded into the report's
    `identifier_counts[NAME]`.
    """

    def __init__(
        self,
        engine: SafeHarborEngine | None = None,
        overlay: NerDeidOverlay | None = None,
    ) -> None:
        self._engine = engine or SafeHarborEngine()
        self._overlay = overlay

    async def deidentify(
        self,
        note: RawClinicalNote,
        *,
        pseudo_id: PatientPseudoId | None = None,
    ) -> tuple[DeidentificationReport, SafeClinicalContext]:
        pid = pseudo_id or _new_pseudo_id()
        report, ctx = self._engine.deidentify_note(note, pseudo_id=pid)
        if self._overlay is not None:
            cleaned, added = self._overlay.apply(ctx.cleaned_text)
            if added:
                counts = dict(report.identifier_counts)
                counts[SafeHarborIdentifier.NAME] = (
                    counts.get(SafeHarborIdentifier.NAME, 0) + added
                )
                report = report.model_copy(update={"identifier_counts": counts})
                ctx = ctx.model_copy(update={"cleaned_text": cleaned})
                report.notes.append(
                    f"NER overlay added {added} NAME redactions."
                )
        return report, ctx


def _new_pseudo_id() -> PatientPseudoId:
    # 16 hex chars = 64 bits of entropy; collision-free for any realistic load.
    return f"pid_{token_hex(8)}"


__all__ = ["DeidentificationService", "SafeHarborService"]
