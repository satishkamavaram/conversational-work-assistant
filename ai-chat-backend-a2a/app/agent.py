from __future__ import annotations

from collections.abc import AsyncIterator

from app.models import AgentReply, AgentStreamEvent, UploadedFile
from app.services.strands_agent_service import StrandsAgentService


class CopilotConceptAgent:
    def __init__(self) -> None:
        self._strands = StrandsAgentService()

    async def reply(
        self,
        query: str,
        uploads: list[UploadedFile],
        authorization_header: str | None = None,
        trace_session_id: str | None = None,
    ) -> AgentReply:
        return await self._strands.reply(
            query,
            uploads,
            authorization_header,
            trace_session_id,
        )

    async def stream_reply(
        self,
        query: str,
        uploads: list[UploadedFile],
        authorization_header: str | None = None,
        trace_session_id: str | None = None,
    ) -> AsyncIterator[AgentStreamEvent]:
        async for event in self._strands.stream_reply(
            query,
            uploads,
            authorization_header,
            trace_session_id,
        ):
            yield event
