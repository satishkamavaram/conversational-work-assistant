from __future__ import annotations

import logging

import uvicorn

from a2a.server.apps import A2AStarletteApplication
from a2a.server.request_handlers import DefaultRequestHandler
from a2a.server.tasks import InMemoryTaskStore
from a2a.types import AgentCapabilities, AgentCard, AgentSkill
from starlette.applications import Starlette
from starlette.middleware.cors import CORSMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

from app.config import settings
from app.executor import CopilotConceptExecutor

logging.basicConfig(
    level=getattr(logging, settings.log_level.upper(), logging.INFO),
    format='%(asctime)s %(levelname)s %(name)s %(message)s',
)


def build_agent_card() -> AgentCard:
    return AgentCard(
        name='Copilot Concepts Strands Agent',
        description='A Strands-powered A2A backend that uses LiteLLM/OpenAI and MCP tools for the paired frontend/backend project.',
        url=settings.public_base_url,
        version='1.0.0',
        default_input_modes=['text'],
        default_output_modes=['text', 'file'],
        capabilities=AgentCapabilities(streaming=True),
        skills=[
            AgentSkill(
                id='copilot-concepts-strands-agent',
                name='Copilot Concepts Strands Agent',
                description='Answers requests with a Strands agent and uses MCP tools for file and workflow operations.',
                tags=['copilot', 'a2a', 'frontend', 'backend', 'strands', 'mcp'],
                examples=[
                    'Summarize the available MCP tools.',
                    'Download a CV document and return it as a file.',
                ],
            )
        ],
    )


def build_app() -> Starlette:
    agent_card = build_agent_card()
    handler = DefaultRequestHandler(
        agent_executor=CopilotConceptExecutor(),
        task_store=InMemoryTaskStore(),
    )
    app = A2AStarletteApplication(
        agent_card=agent_card,
        http_handler=handler,
    ).build()

    app.add_middleware(
        CORSMiddleware,
        allow_origins=[settings.cors_origin],
        allow_methods=['GET', 'POST', 'OPTIONS'],
        allow_headers=['*'],
    )

    async def healthz(request: Request) -> JSONResponse:
        return JSONResponse({'status': 'ok'})

    app.add_route('/healthz', healthz, methods=['GET'])

    return app


def main() -> None:
    if not logging.getLogger().handlers:
        logging.basicConfig(
            level=logging.INFO,
            format='%(asctime)s %(levelname)s [%(name)s] %(message)s',
        )
    uvicorn.run(build_app(), host=settings.host, port=settings.port)


if __name__ == '__main__':
    main()
