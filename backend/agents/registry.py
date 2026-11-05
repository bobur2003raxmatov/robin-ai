"""Tool registry used by the executor (and exposed to AI models as function-calling tools)."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable


@dataclass
class ToolContext:
    user_id: str
    task_id: str = ""
    conversation_id: str = ""
    brain: Any = None
    memory: Any = None
    device_id: str = ""


@dataclass
class Tool:
    name: str
    description: str
    parameters: dict
    func: Callable[..., Awaitable[Any]]
    risk: str = "low"           # safe | low | medium | high | critical
    module: str = ""            # permission module key
    computer: bool = False      # runs on the user's computer (local or via desktop agent)
    agents: tuple = ()          # specialist agents that get this tool ("" = all)

    def schema(self) -> dict:
        return {"name": self.name, "description": self.description, "parameters": self.parameters}


TOOLS: dict[str, Tool] = {}


def tool(name: str, description: str, properties: dict | None = None, required: list | None = None,
         risk: str = "low", module: str = "", computer: bool = False, agents: tuple = ()):
    def deco(fn):
        TOOLS[name] = Tool(name=name, description=description,
                           parameters={"type": "object", "properties": properties or {},
                                       "required": required or []},
                           func=fn, risk=risk, module=module, computer=computer, agents=agents)
        return fn
    return deco


def S(desc: str, type_: str = "string", **kw) -> dict:
    d = {"type": type_, "description": desc}
    d.update(kw)
    return d


def tools_for(agent: str, perms: dict) -> list[dict]:
    out = []
    for t in TOOLS.values():
        if t.module and perms.get(t.module) is False:
            continue
        if t.agents and agent not in t.agents and agent != "assistant":
            continue
        out.append(t.schema())
    return out
