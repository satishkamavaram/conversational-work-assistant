from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class UploadedFile:
    name: str
    mime_type: str
    bytes_base64: str


@dataclass(frozen=True)
class GeneratedFile:
    name: str
    mime_type: str
    bytes_base64: str


@dataclass(frozen=True)
class AgentReply:
    content: str
    files: list[GeneratedFile] = field(default_factory=list)
