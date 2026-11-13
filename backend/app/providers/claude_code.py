"""Adapter that answers through the Claude Code command line on this computer (`claude -p`).

For local testing and demos only: it uses whoever is logged in to Claude Code here, so it is
switched on by CLAUDE_CODE_LOCAL in .env and never offered on a deployed server. Each call runs
in an empty temporary folder with every tool, MCP server, skill and settings file switched off,
so the model can only answer; it cannot touch this computer.
"""

from __future__ import annotations

import asyncio
import json
import tempfile

from pydantic import BaseModel

from app.providers.model_client import Message, Overloaded, RateLimited, Rejected, Reply

TIMEOUT_S = 180.0
SYSTEM = "You answer with the requested JSON only."


class ClaudeCodeClient:
    def __init__(self, *, command: str = "claude", timeout_s: float = TIMEOUT_S) -> None:
        self._command, self._timeout = command or "claude", timeout_s
        self._workdir = tempfile.mkdtemp(prefix="lede-claude-")

    async def reply(
        self, model: str, system: str, messages: list[Message], schema: type[BaseModel]
    ) -> Reply:
        args = [
            self._command,
            "-p",
            "--output-format", "json",
            "--json-schema", json.dumps(schema.model_json_schema(), separators=(",", ":")),
            "--model", model,
            "--system-prompt", system or SYSTEM,
            "--tools", "",
            "--no-session-persistence",
            "--strict-mcp-config",
            "--disable-slash-commands",
            "--setting-sources", "",
        ]  # fmt: skip
        try:
            proc = await asyncio.create_subprocess_exec(
                *args,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=self._workdir,
            )
        except OSError as exc:
            raise Rejected(f"cannot run {self._command!r}: {exc}") from exc
        try:
            out, _ = await asyncio.wait_for(
                proc.communicate(_as_prompt(messages).encode()), self._timeout
            )
        except TimeoutError as exc:
            proc.kill()
            raise Overloaded("timed out") from exc
        try:
            data = json.loads(out)
        except json.JSONDecodeError as exc:
            raise Overloaded(f"unreadable output (exit {proc.returncode})") from exc
        if data.get("is_error"):
            status = data.get("api_error_status") or 0
            if status == 429:
                raise RateLimited()
            if status >= 500:
                raise Overloaded(str(status))
            raise Rejected(str(data.get("result") or status)[:200])
        structured = data.get("structured_output")
        usage = data.get("usage") or {}
        return Reply(
            content=json.dumps(structured) if structured is not None else data.get("result", ""),
            prompt_tokens=usage.get("input_tokens", 0),
            completion_tokens=usage.get("output_tokens", 0),
        )


def _as_prompt(messages: list[Message]) -> str:
    """The CLI takes one prompt; a corrective retry folds the earlier turns into it."""
    if len(messages) == 1:
        return messages[0]["content"]
    turns = {"user": "REQUEST", "assistant": "YOUR EARLIER ANSWER"}
    return "\n\n".join(f"{turns[m['role']]}:\n{m['content']}" for m in messages)
