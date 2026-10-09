# tests/unit/test_shared_inference.py
"""Отказы и несовместимые ответы внешнего CV API не превращаются в ложные нарушения."""

from datetime import UTC, datetime
from unittest.mock import Mock

import httpx
import pytest

from infrastructure.inference import SharedPersonDetector


@pytest.mark.parametrize(
    "change",
    [
        {"camera_id": "other-camera"},
        {"session_id": "other-session"},
        {"sequence": 7},
        {"tracks": [{"track_id": 1, "confidence": 0.9, "bbox": [-1, 0, 1, 1]}]},
        {"tracks": [{"track_id": 1, "confidence": 0.9, "bbox": [0.9, 0, 0.1, 1]}]},
        {"tracks": [{"track_id": 1, "confidence": 0.9, "bbox": [0, 0, 1, 1]}] * 2},
        {"tracks": [{"track_id": True, "confidence": 0.9, "bbox": [0, 0, 1, 1]}]},
        {"version": 2},
    ],
)
def test_shared_response_must_match_camera_session_and_valid_geometry(change):
    """Отклоняет чужой кадр, несовместимую версию, неверные bbox и повторные ID."""
    payload = {
        "version": 1,
        "camera_id": "camera-1",
        "session_id": "session-1",
        "sequence": 1,
        "tracks": [],
        **change,
    }
    with httpx.Client(
        transport=httpx.MockTransport(lambda request: httpx.Response(200, json=payload))
    ) as client:
        detector = SharedPersonDetector(
            client,
            "http://shared-cv/v1/person-tracks",
            "",
            "camera-1",
            "session-1",
            Mock(original=Mock(return_value=b"jpeg")),
            2,
        )
        with pytest.raises(RuntimeError, match="shared_inference_unavailable_or_invalid"):
            detector.detect("frame", datetime.now(UTC))


def test_inference_http_failure_redacts_token_body_and_url():
    """Внешний отказ скрывает токен, payload провайдера и адрес endpoint."""
    with httpx.Client(
        transport=httpx.MockTransport(lambda request: httpx.Response(503, text="private-response"))
    ) as client:
        detector = SharedPersonDetector(
            client,
            "http://private-host/v1/person-tracks",
            "private-token",
            "camera-1",
            "session-1",
            Mock(original=Mock(return_value=b"jpeg")),
            2,
        )
        with pytest.raises(RuntimeError) as error:
            detector.detect("frame", datetime.now(UTC))
        assert all(
            secret not in str(error.value)
            for secret in ("private-token", "private-response", "private-host")
        )
