from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Literal

Risk = Literal["read", "write"]


class ToolError(Exception):
    """Base error for the MCP-style tool layer."""


class UnknownTool(ToolError):
    pass


class PermissionDenied(ToolError):
    """Raised whenever a write is attempted outside the approval gate."""


@dataclass(slots=True)
class Tool:
    name: str
    description: str
    risk: Risk
    input_schema: dict[str, Any]
    handler: Callable[..., dict[str, Any]]
    undo_handler: Callable[[dict[str, Any]], None] | None = None
    undo_builder: Callable[[dict[str, Any]], dict[str, Any] | None] | None = None

    def public(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "risk": self.risk,
            "input_schema": self.input_schema,
            "undoable": self.undo_handler is not None,
        }


class Registry:
    """Tool registry with a hard read/write split.

    Reads may run freely. Writes are only reachable through ``execute_write`` and
    require an approved action id, which only the approval gate can issue.
    """

    def __init__(self) -> None:
        self._tools: dict[str, Tool] = {}

    def register(self, tool: Tool) -> None:
        if tool.name in self._tools:
            raise ToolError(f"duplicate tool {tool.name}")
        self._tools[tool.name] = tool

    def get(self, name: str) -> Tool:
        try:
            return self._tools[name]
        except KeyError as exc:
            raise UnknownTool(f"unknown tool: {name}") from exc

    def read(self, name: str, **kwargs: Any) -> dict[str, Any]:
        tool = self.get(name)
        if tool.risk != "read":
            raise PermissionDenied(
                f"{name} is a write tool; it requires a user-approved action"
            )
        return tool.handler(**kwargs)

    def execute_write(
        self, name: str, args: dict[str, Any], *, approval_id: str | None
    ) -> dict[str, Any]:
        if not approval_id:
            raise PermissionDenied(
                f"{name} is a write tool; an approved action id is required"
            )
        tool = self.get(name)
        if tool.risk != "write":
            raise ToolError(f"{name} is not a write tool")
        return tool.handler(**args)

    def undo(self, name: str, data: dict[str, Any]) -> None:
        tool = self.get(name)
        if tool.undo_handler is None:
            raise ToolError(f"{name} is not undoable")
        tool.undo_handler(data)

    def catalog(self) -> list[dict[str, Any]]:
        return [tool.public() for tool in self._tools.values()]

    def write_names(self) -> set[str]:
        return {name for name, tool in self._tools.items() if tool.risk == "write"}
