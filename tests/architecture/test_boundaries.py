# tests/architecture/test_boundaries.py
"""AST и URL проверки слоёв, ORM, constructor injection, CBV и frontend invariants."""

import ast
import re
from pathlib import Path

from django.urls import get_resolver

ROOT = Path(__file__).resolve().parents[2]


def test_application_domain_dependencies():
    """Внутренние слои не импортируют frameworks, concrete infrastructure или container."""
    forbidden = (
        "django",
        "rest_framework",
        "celery",
        "redis",
        "cv2",
        "ultralytics",
        "httpx",
        "requests",
    )
    for path in [*(ROOT / "src/application").rglob("*.py"), *(ROOT / "src/domain").rglob("*.py")]:
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            names = (
                [item.name for item in node.names]
                if isinstance(node, ast.Import)
                else [node.module or ""]
                if isinstance(node, ast.ImportFrom)
                else []
            )
            for name in names:
                assert (
                    not name.startswith(forbidden)
                    and ".infrastructure" not in name
                    and name != "core.container"
                ), (path, name)
            if isinstance(node, ast.Attribute):
                assert node.attr not in ("objects", "select_related", "prefetch_related"), (
                    path,
                    node.attr,
                )


def test_http_endpoints_are_cbv():
    """Каждый project URL, включая health/stream, подключён через class .as_view()."""
    for route in get_resolver().url_patterns:
        assert getattr(route.callback, "view_class", None), route


def test_transport_and_workers_do_not_construct_adapters():
    """HTTP transport не читает ORM; worker использует только root factories и injected ports."""
    paths = list((ROOT / "src/interface").glob("*.py")) + list((ROOT / "src/workers").glob("*.py"))
    for path in paths:
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                assert ".infrastructure" not in (node.module or ""), (path, node.module)
                assert not (node.module or "").endswith("models"), (path, node.module)
            if isinstance(node, ast.Attribute):
                assert node.attr not in ("objects", "select_related", "prefetch_related"), (
                    path,
                    node.attr,
                )


def test_project_python_docs_are_present():
    """Каждый Python module, class и function имеет русскоязычную документацию."""
    for path in (ROOT / "src").rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
                doc = ast.get_docstring(node)
                assert doc and re.search("[А-Яа-яЁё]", doc), (path, getattr(node, "name", "module"))


def test_frontend_contracts():
    """Скрипты расположены в head, defer сохранён, raw innerHTML и inline handlers отсутствуют."""
    base = (ROOT / "templates/base.html").read_text(encoding="utf-8")
    assert base.index('rel="stylesheet"') < base.index("<script") < base.index("</head>")
    for path in (ROOT / "templates").rglob("*.html"):
        content = path.read_text(encoding="utf-8")
        assert not re.search(r"\son\w+\s*=", content, re.I), path
        assert "<style" not in content, path
        for script in re.findall(r"<script\b[^>]*>", content):
            assert "defer" in script and "src=" in script, path
    for path in (ROOT / "static/js").rglob("*.js"):
        assert ".innerHTML" not in path.read_text(encoding="utf-8"), path


def test_runtime_does_not_import_archived_packages():
    """Рабочие модули не возвращаются к старым именам после переноса слоёв."""
    obsolete = ("modules", "web", "legacy")
    for path in (ROOT / "src").rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            names = (
                [item.name for item in node.names]
                if isinstance(node, ast.Import)
                else [node.module or ""]
                if isinstance(node, ast.ImportFrom)
                else []
            )
            for name in names:
                assert not name.startswith(obsolete), (path, name)


def test_project_runtime_has_no_local_model_or_physical_gpu_dependencies():
    """Бизнес-проект использует CPU-захват и shared CV API без локальных моделей или CUDA."""
    forbidden = ("ultralytics", "torch", "torchvision", "vllm", "cupy")
    for path in (ROOT / "src").rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                assert not any(item.name.startswith(forbidden) for item in node.names), path
            elif isinstance(node, ast.ImportFrom):
                assert not (node.module or "").startswith(forbidden), path
    compose = (ROOT / "compose.yaml").read_text(encoding="utf-8")
    assert "driver: nvidia" not in compose and "device_ids:" not in compose
    assert "VISION_GPU_ID" not in compose and "./models" not in compose
