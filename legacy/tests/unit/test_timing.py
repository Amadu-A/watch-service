# tests/unit/test_timing.py
"""Общий timing decorator: sync/async успех и ошибка без потери metadata."""

import asyncio
import logging

import pytest

from core.timing import timed


@pytest.mark.parametrize("asynchronous", [False, True])
@pytest.mark.parametrize("fail", [False, True])
def test_timing_metadata_and_status(caplog, asynchronous, fail):
    """Каждый вызов пишет одно событие с неотрицательной duration и корректным status."""

    def operation():
        """Имитирует значимую operation с управляемым исходом."""
        if fail:
            raise ValueError("expected")
        return 42

    async def async_operation():
        """Предоставляет тот же контракт для async timing branch."""
        return operation()

    target = timed("test_operation")(async_operation if asynchronous else operation)
    with caplog.at_level(logging.INFO):
        if fail:
            with pytest.raises(ValueError):
                asyncio.run(target()) if asynchronous else target()
        else:
            assert (asyncio.run(target()) if asynchronous else target()) == 42
    assert target.__name__ == ("async_operation" if asynchronous else "operation")
    records = [
        record for record in caplog.records if getattr(record, "event", "") == "operation_timing"
    ]
    assert len(records) == 1
    assert records[0].duration_ms >= 0
    assert records[0].status == ("error" if fail else "success")
