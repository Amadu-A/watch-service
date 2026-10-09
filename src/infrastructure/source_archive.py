# src/infrastructure/source_archive.py
"""Архив исходного кода текущей сборки: только явный список публичных файлов проекта."""

import io
import tarfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

PUBLIC_FILES = (
    "README.md",
    "LICENSE",
    "docs-specification.md",
    "pyproject.toml",
    "uv.lock",
    ".env.example",
    ".gitignore",
    ".gitattributes",
    ".dockerignore",
    ".python-version",
    "manage.py",
    "package.json",
    "Dockerfile",
    "Dockerfile.bootstrap",
    "compose.yaml",
    "compose.bootstrap.yaml",
    "compose.gpu.yaml",
)
PUBLIC_DIRECTORIES = ("src", "templates", "static", "tests", "scripts", "docs", ".github")


def source_bytes(root: Path = ROOT) -> bytes:
    """Собирает исходники без .env, credentials, моделей, media, Git history и bytecode."""
    output = io.BytesIO()
    paths = [root / name for name in PUBLIC_FILES if (root / name).is_file()]
    for name in PUBLIC_DIRECTORIES:
        paths.extend(path for path in (root / name).rglob("*") if path.is_file())
    with tarfile.open(fileobj=output, mode="w:gz") as archive:
        for path in sorted(paths):
            relative = path.relative_to(root)
            if (
                path.is_symlink()
                or "__pycache__" in relative.parts
                or path.suffix in (".pyc", ".pyo")
            ):
                continue
            archive.add(
                path, arcname=f"warehouse-perimeter-watch/{relative.as_posix()}", recursive=False
            )
    return output.getvalue()


def running_source() -> bytes:
    """Возвращает архив сборки из Docker image, а при локальной разработке — текущие файлы."""
    built = ROOT / "source.tar.gz"
    return built.read_bytes() if built.is_file() else source_bytes()


if __name__ == "__main__":
    (ROOT / "source.tar.gz").write_bytes(source_bytes())
