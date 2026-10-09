# tests/architecture/test_source.py
"""Архив публикуемой версии не содержит runtime secrets или данные видеонаблюдения."""

import io
import tarfile

from infrastructure.source_archive import source_bytes


def test_source_archive_uses_allowlist(tmp_path):
    """Публичные файлы включаются; приватный .env, media и модели остаются вне архива."""
    (tmp_path / "README.md").write_text("Описание", encoding="utf-8")
    (tmp_path / ".env").write_text("SECRET=must-not-be-published", encoding="utf-8")
    (tmp_path / "media").mkdir()
    (tmp_path / "media/evidence.jpg").write_bytes(b"private-image")
    (tmp_path / "src").mkdir()
    (tmp_path / "src/main.py").write_text("print('project')", encoding="utf-8")
    data = source_bytes(tmp_path)
    with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as archive:
        names = archive.getnames()
        assert names == [
            "warehouse-perimeter-watch/README.md",
            "warehouse-perimeter-watch/src/main.py",
        ]
        assert b"must-not-be-published" not in b"".join(
            archive.extractfile(name).read() for name in names
        )
