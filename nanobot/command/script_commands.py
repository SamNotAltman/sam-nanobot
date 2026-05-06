"""Static script-backed slash commands loaded from JSON."""

from __future__ import annotations

import asyncio
from contextlib import suppress
import json
import os
import re
import sys
from dataclasses import dataclass
from pathlib import Path

from loguru import logger

from nanobot.bus.events import OutboundMessage
from nanobot.command.router import CommandContext, CommandRouter

DEFAULT_TELEGRAM_SCRIPT_COMMANDS_PATH = Path(
    os.environ.get(
        "NANOBOT_TELEGRAM_SCRIPT_COMMANDS_PATH",
        "/Users/sam/.nanobot/telegram_script_commands.json",
    )
).expanduser()
_VALID_COMMAND_RE = re.compile(r"^[a-z0-9_]{1,32}$")
_SCRIPT_TIMEOUT_SECONDS = 60
_MAX_OUTPUT_CHARS = 8000


@dataclass(frozen=True)
class ScriptCommand:
    """A validated script-backed slash command definition."""

    command: str
    script: str
    description: str


def load_script_commands(path: str | Path = DEFAULT_TELEGRAM_SCRIPT_COMMANDS_PATH) -> list[ScriptCommand]:
    """Load and validate script-backed slash commands from *path*."""
    config_path = Path(path).expanduser()
    try:
        payload = json.loads(config_path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        logger.info("Telegram script commands config not found: {}", config_path)
        return []
    except Exception as e:
        logger.warning("Failed to load Telegram script commands from {}: {}", config_path, e)
        return []

    raw_commands = payload.get("commands")
    if not isinstance(raw_commands, list):
        logger.warning("Telegram script commands config has invalid 'commands' list: {}", config_path)
        return []

    commands: list[ScriptCommand] = []
    seen: set[str] = set()
    for idx, entry in enumerate(raw_commands):
        if not isinstance(entry, dict):
            logger.warning("Skipping Telegram script command #{}: entry is not an object", idx)
            continue

        command = str(entry.get("command") or "").strip().lower()
        script = str(entry.get("script") or "").strip()
        description = str(entry.get("description") or "").strip()

        if not command or not script or not description:
            logger.warning("Skipping Telegram script command #{}: command/script/description is required", idx)
            continue
        if not _VALID_COMMAND_RE.fullmatch(command):
            logger.warning("Skipping Telegram script command '{}': invalid Telegram command name", command)
            continue
        if command in seen:
            logger.warning("Skipping duplicate Telegram script command '{}'", command)
            continue

        seen.add(command)
        commands.append(ScriptCommand(command=command, script=script, description=description))

    return commands


def register_script_commands(
    router: CommandRouter,
    *,
    path: str | Path = DEFAULT_TELEGRAM_SCRIPT_COMMANDS_PATH,
) -> list[ScriptCommand]:
    """Register JSON-backed script commands on *router*."""
    commands = load_script_commands(path)
    for cmd in commands:
        router.exact(f"/{cmd.command}", _make_script_handler(cmd))
        router.prefix(f"/{cmd.command} ", _make_script_handler(cmd))
    return commands


def build_script_help_lines(
    *,
    path: str | Path = DEFAULT_TELEGRAM_SCRIPT_COMMANDS_PATH,
) -> list[str]:
    """Return help lines for configured script commands."""
    return [f"/{cmd.command} — {cmd.description}" for cmd in load_script_commands(path)]


def _make_script_handler(command: ScriptCommand):
    async def _handler(ctx: CommandContext) -> OutboundMessage:
        return await _execute_script_command(ctx, command)

    return _handler


async def _execute_script_command(ctx: CommandContext, command: ScriptCommand) -> OutboundMessage:
    """Execute a script-backed command and return its output."""
    metadata = {**dict(ctx.msg.metadata or {}), "render_as": "text"}
    script_path = Path(command.script).expanduser()

    if ctx.args.strip():
        return OutboundMessage(
            channel=ctx.msg.channel,
            chat_id=ctx.msg.chat_id,
            content=f"`/{command.command}` does not accept arguments.",
            metadata=metadata,
        )

    if not script_path.exists():
        return OutboundMessage(
            channel=ctx.msg.channel,
            chat_id=ctx.msg.chat_id,
            content=f"Script not found: `{script_path}`",
            metadata=metadata,
        )

    process: asyncio.subprocess.Process | None = None
    try:
        process = await asyncio.create_subprocess_exec(
            sys.executable,
            str(script_path),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=str(script_path.parent),
        )
        stdout, stderr = await asyncio.wait_for(
            process.communicate(),
            timeout=_SCRIPT_TIMEOUT_SECONDS,
        )
    except asyncio.TimeoutError:
        if process is not None:
            with suppress(ProcessLookupError):
                process.kill()
            with suppress(Exception):
                await process.wait()
        return OutboundMessage(
            channel=ctx.msg.channel,
            chat_id=ctx.msg.chat_id,
            content=f"`/{command.command}` timed out after {_SCRIPT_TIMEOUT_SECONDS}s.",
            metadata=metadata,
        )
    except Exception as e:
        logger.warning("Script command /{} failed to start: {}", command.command, e)
        return OutboundMessage(
            channel=ctx.msg.channel,
            chat_id=ctx.msg.chat_id,
            content=f"Failed to run `/{command.command}`: {e}",
            metadata=metadata,
        )

    text = _format_script_output(command, process.returncode, stdout, stderr)
    return OutboundMessage(
        channel=ctx.msg.channel,
        chat_id=ctx.msg.chat_id,
        content=text,
        metadata=metadata,
    )


def _format_script_output(command: ScriptCommand, returncode: int, stdout: bytes, stderr: bytes) -> str:
    stdout_text = stdout.decode("utf-8", errors="replace").strip()
    stderr_text = stderr.decode("utf-8", errors="replace").strip()

    lines = [f"`/{command.command}`"]
    if stdout_text:
        lines.extend(["", stdout_text])
    if stderr_text:
        lines.extend(["", "STDERR:", stderr_text])
    if returncode != 0:
        lines.extend(["", f"Exit code: {returncode}"])
    if len(lines) == 1:
        lines.extend(["", "(no output)"])

    text = "\n".join(lines)
    if len(text) > _MAX_OUTPUT_CHARS:
        text = text[: _MAX_OUTPUT_CHARS - 1] + "…"
    return text
