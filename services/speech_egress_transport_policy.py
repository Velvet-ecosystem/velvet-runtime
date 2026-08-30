# SPDX-License-Identifier: GPL-3.0-only
"""Runtime policy wrapper for Audio speech HTTP acknowledgement truth."""

from __future__ import annotations

from services.speech_expression_egress import (
    AudioSpeechHttpTransport,
    SpeechEgressRecord,
    SpeechTransportResult,
)


class ReceiptVerifiedAudioSpeechHttpTransport(AudioSpeechHttpTransport):
    """Accept Audio success only when a durable receipt identifier is present.

    Audio Studio's current endpoint always returns a receipt for both fresh 202
    acceptance and duplicate 409 acceptance. Runtime therefore keeps the exact
    pending envelope if a peer ever claims acceptance without supplying that
    durable evidence.
    """

    def send(self, record: SpeechEgressRecord) -> SpeechTransportResult:
        result = super().send(record)
        if result.accepted and not result.receipt_id:
            return SpeechTransportResult(
                accepted=False,
                terminal=False,
                receipt_id=None,
                detail="Audio acceptance omitted durable receipt_id",
            )
        return result
