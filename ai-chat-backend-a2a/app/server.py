from __future__ import annotations

import uvicorn

from a2a.server.apps import A2AStarletteApplication
from a2a.server.request_handlers import DefaultRequestHandler
from a2a.server.tasks import InMemoryTaskStore
from a2a.types import AgentCapabilities, AgentCard, AgentSkill
from starlette.middleware.cors import CORSMiddleware
from starlette.responses import JSONResponse

from app.config import settings
from app.executor import CopilotConceptExecutor


def build_agent_card() -> AgentCard:
    return AgentCard(
        name='Copilot Customization Guide Agent',
        description='A demonstration A2A backend that explains custom instructions, custom agents, agent skills, and subagents for the paired frontend/backend project.',
        url=settings.public_base_url,
        version='1.0.0',
        default_input_modes=['text'],
        default_output_modes=['text'],
        capabilities=AgentCapabilities(streaming=False),
        skills=[
            AgentSkill(
                id='copilot-customization-guide',
                name='Copilot Customization Guide',
                description='Explains how to apply Copilot customization features in this frontend/backend setup and can export a study guide file.',
                tags=['copilot', 'a2a', 'frontend', 'backend'],
                examples=[
                    'Explain custom agents versus skills in this project.',
                    'Export a study guide for custom instructions and subagents.',
                ],
            )
        ],
    )


def build_app():
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

    @app.route('/healthz', methods=['GET'])
    async def healthz(request):
        return JSONResponse({'status': 'ok'})

    return app


def main() -> None:
    uvicorn.run(build_app(), host=settings.host, port=settings.port)


if __name__ == '__main__':
    main()
