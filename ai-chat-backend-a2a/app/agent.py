from __future__ import annotations

from app.config import settings
from app.models import AgentReply, UploadedFile
from app.services.concept_guide_service import ConceptGuideService
from app.services.strands_agent_service import StrandsAgentService


class CopilotConceptAgent:
    def __init__(self) -> None:
        self._guide = ConceptGuideService()
        self._strands = (
            StrandsAgentService() if settings.agent_mode == 'strands' else None
        )

    async def reply(
        self,
        query: str,
        uploads: list[UploadedFile],
        authorization_header: str | None = None,
    ) -> AgentReply:
        if settings.agent_mode == 'guide':
            return self._guide.reply(query, uploads)
        if settings.agent_mode == 'strands' and self._strands:
            return await self._strands.reply(query, uploads, authorization_header)
        raise ValueError(
            f'Unsupported A2A_AGENT_MODE: {settings.agent_mode}. Expected "guide" or "strands".'
        )
