# src/modules/reports/infrastructure/renderer.py
"""Русскоязычные PDF/CSV с Unicode-font, фотографиями и безопасным текстом."""

import csv
import io
from datetime import datetime
from pathlib import Path
from xml.sax.saxutils import escape
from zoneinfo import ZoneInfo

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import Image, Paragraph, SimpleDocTemplate, Spacer

from core.domain import BusinessError


class EvidenceReportRenderer:
    """Рендерит DTO с историческим camera snapshot, не обращаясь к ORM."""

    def __init__(self, storage, timezone_provider, font_path: str = ""):
        """Получает storage и provider timezone; шрифт выбирается из deployment paths."""
        self.storage, self.timezone_provider = storage, timezone_provider
        candidates = [
            font_path,
            "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
            "C:/Windows/Fonts/arial.ttf",
        ]
        self.font = next((path for path in candidates if path and Path(path).is_file()), None)

    def _time(self, event: dict) -> str:
        """Форматирует UTC timestamp в timezone объекта, сохраняя точный момент события."""
        zone = self.timezone_provider()
        return (
            datetime.fromisoformat(event["detected_at"])
            .astimezone(ZoneInfo(zone))
            .strftime("%d.%m.%Y %H:%M:%S")
            + f" ({zone})"
        )

    def pdf(self, events: list[dict]) -> bytes:
        """Встраивает Unicode font и annotated image, чтобы кириллица читалась вне сервера."""
        if self.font is None:
            raise BusinessError("report_font_missing", "Unicode-шрифт отчёта недоступен.", 503)
        if "WarehouseUnicode" not in pdfmetrics.getRegisteredFontNames():
            pdfmetrics.registerFont(TTFont("WarehouseUnicode", self.font))
        style = ParagraphStyle(
            "body",
            fontName="WarehouseUnicode",
            fontSize=9,
            leading=14,
            textColor=colors.HexColor("#162030"),
        )
        output = io.BytesIO()
        story = [Paragraph("Склад. Видеоконтроль — отчёт о нарушениях", style), Spacer(1, 16)]
        if not events:
            story.append(Paragraph("За выбранный период нарушений нет.", style))
        for event in events:
            values = [
                f"Событие: {event['id']}",
                f"Камера: {event['camera']['name']}",
                f"Место: {event['camera'].get('location', '')}",
                f"Дата: {self._time(event)}",
                "Направление: "
                + ("Вход на территорию" if event["direction"] == "ENTRY" else "Выход с территории"),
                f"Уверенность: {event['confidence']:.2f}; track_id: {event['track_id']}",
                "Уведомления: "
                + ", ".join(f"{item['channel']}: {item['status']}" for item in event["deliveries"]),
            ]
            story.extend(Paragraph(escape(value), style) for value in values)
            image = Image(io.BytesIO(self.storage.read(event["media_paths"]["annotated"])))
            ratio = min(470 / image.imageWidth, 240 / image.imageHeight)
            image.drawWidth, image.drawHeight = image.imageWidth * ratio, image.imageHeight * ratio
            story.extend([Spacer(1, 8), image, Spacer(1, 18)])
        SimpleDocTemplate(
            output, pagesize=A4, title="Отчёт видеоконтроля", author="Warehouse Perimeter Watch"
        ).build(story)
        return output.getvalue()

    def csv(self, events: list[dict]) -> bytes:
        """Экранирует опасные spreadsheet префиксы и добавляет BOM для Windows Excel."""
        output = io.StringIO(newline="")
        writer = csv.writer(output, delimiter=";")
        writer.writerow(["ID", "Камера", "Место", "Дата и время", "Направление", "Confidence"])
        for event in events:
            values = [
                event["id"],
                event["camera"]["name"],
                event["camera"].get("location", ""),
                self._time(event),
                event["direction"],
                event["confidence"],
            ]
            writer.writerow(
                [
                    "'" + str(value)
                    if str(value).lstrip().startswith(("=", "+", "-", "@"))
                    else value
                    for value in values
                ]
            )
        return output.getvalue().encode("utf-8-sig")
