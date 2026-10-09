# tests/unit/test_frame_renderer.py
"""Настоящее кодирование JPEG и рисование разметки без камер и model internals."""

import io

import numpy as np
from PIL import Image

from infrastructure.vision import OpenCVFrameRenderer


def test_frame_renderer_preserves_original_and_draws_normalized_geometry():
    """Размеченный JPEG содержит line и bbox; исходный frame остаётся неизменным."""
    frame = np.zeros((240, 400, 3), dtype=np.uint8)
    frame[:, :] = [35, 25, 15]
    previous = frame.copy()
    renderer = OpenCVFrameRenderer()
    original = renderer.original(frame)
    annotated = renderer.annotated(
        frame,
        [{"track_id": 7, "confidence": 0.91, "bbox": [0.4, 0.2, 0.6, 0.7]}],
        {"enabled": True, "start": {"x": 0.2, "y": 0.5}, "end": {"x": 0.8, "y": 0.5}},
        "Главный вход | 07.10.2026 23:10:00 | ENTRY",
    )
    assert original.startswith(b"\xff\xd8") and annotated.startswith(b"\xff\xd8")
    assert np.array_equal(frame, previous)
    source = Image.open(io.BytesIO(original))
    evidence = Image.open(io.BytesIO(annotated))
    assert source.size == evidence.size == (400, 240)
    red, green, blue = evidence.getpixel((120, 120))
    assert red > green + 50 and red > blue + 50
    assert source.getpixel((120, 120)) != evidence.getpixel((120, 120))


def test_empty_optional_clip_does_not_create_file():
    """Отсутствие кадров clip возвращает None и не препятствует JPEG evidence."""
    assert OpenCVFrameRenderer().clip([], 5) is None
