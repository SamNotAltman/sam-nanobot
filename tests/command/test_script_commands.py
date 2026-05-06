from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from nanobot.command.router import CommandContext, CommandRouter
from nanobot.command.script_commands import ScriptCommand, register_script_commands


@pytest.mark.asyncio
async def test_register_script_commands_executes_script(monkeypatch, tmp_path) -> None:
    script = tmp_path / "hello.py"
    script.write_text("print('hello from script')\n", encoding="utf-8")
    config = tmp_path / "telegram_script_commands.json"
    config.write_text(
        '{"commands": [{"command": "stock", "script": "%s", "description": "Stock"}]}' % script,
        encoding="utf-8",
    )

    router = CommandRouter()
    register_script_commands(router, path=config)

    ctx = CommandContext(
        msg=SimpleNamespace(channel="telegram", chat_id="1", metadata={}),
        session=None,
        key="telegram:1",
        raw="/stock",
        loop=MagicMock(),
    )
    result = await router.dispatch(ctx)

    assert result is not None
    assert "hello from script" in result.content
    assert result.metadata["render_as"] == "text"


@pytest.mark.asyncio
async def test_register_script_commands_rejects_arguments(tmp_path) -> None:
    script = tmp_path / "hello.py"
    script.write_text("print('hello from script')\n", encoding="utf-8")
    config = tmp_path / "telegram_script_commands.json"
    config.write_text(
        '{"commands": [{"command": "stock", "script": "%s", "description": "Stock"}]}' % script,
        encoding="utf-8",
    )

    router = CommandRouter()
    register_script_commands(router, path=config)

    ctx = CommandContext(
        msg=SimpleNamespace(channel="telegram", chat_id="1", metadata={}),
        session=None,
        key="telegram:1",
        raw="/stock abc",
        args="abc",
        loop=MagicMock(),
    )
    result = await router.dispatch(ctx)

    assert result is not None
    assert "does not accept arguments" in result.content


@pytest.mark.asyncio
async def test_register_script_commands_reports_missing_script(tmp_path) -> None:
    config = tmp_path / "telegram_script_commands.json"
    config.write_text(
        '{"commands": [{"command": "stock", "script": "%s", "description": "Stock"}]}' % (tmp_path / "missing.py"),
        encoding="utf-8",
    )

    router = CommandRouter()
    register_script_commands(router, path=config)

    ctx = CommandContext(
        msg=SimpleNamespace(channel="telegram", chat_id="1", metadata={}),
        session=None,
        key="telegram:1",
        raw="/stock",
        loop=MagicMock(),
    )
    result = await router.dispatch(ctx)

    assert result is not None
    assert "Script not found" in result.content
