
# tests/regression/test_opencv_rtsp_decoder.py
"""Регрессия RTSP-декодера для версий OpenCV без cv2.setLogLevel."""

import sys
from types import ModuleType
from unittest.mock import Mock

from infrastructure.vision import RTSPCameraSource


def test_decoder_works_without_removed_opencv_logging_api(monkeypatch):
    """Декодер не зависит от отсутствующего метода cv2.setLogLevel."""
    fake_cv2 = ModuleType("cv2")
    fake_cv2.CAP_FFMPEG = 1900
    fake_cv2.CAP_PROP_OPEN_TIMEOUT_MSEC = 53
    fake_cv2.CAP_PROP_READ_TIMEOUT_MSEC = 54

    capture = Mock()
    capture.read.side_effect = [
        (True, "decoded-frame"),
        (False, None),
    ]
    fake_cv2.VideoCapture = Mock(return_value=capture)

    monkeypatch.setitem(sys.modules, "cv2", fake_cv2)

    connection = {
        "url": "rtsp://192.0.2.1:554/Streaming/Channels/101",
        "username": "camera-user",
        "password": "camera-password",
    }

    source = RTSPCameraSource(connection)

    fake_cv2.VideoCapture.assert_called_once_with(
        "rtsp://camera-user:camera-password@192.0.2.1:554/Streaming/Channels/101",
        fake_cv2.CAP_FFMPEG,
        [
            fake_cv2.CAP_PROP_OPEN_TIMEOUT_MSEC,
            5000,
            fake_cv2.CAP_PROP_READ_TIMEOUT_MSEC,
            5000,
        ],
    )

    assert source.read() == "decoded-frame"
    assert source.read() is None

    source.close()
    capture.release.assert_called_once()
