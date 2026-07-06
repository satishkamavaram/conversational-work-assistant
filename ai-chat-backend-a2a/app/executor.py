from __future__ import annotations

from uuid import uuid4

from typing_extensions import override

from a2a.server.agent_execution import AgentExecutor, RequestContext
from a2a.server.events.event_queue import EventQueue
from a2a.types import (
    Artifact,
    FilePart,
    FileWithBytes,
    Part,
    TaskArtifactUpdateEvent,
    TaskState,
    TaskStatus,
    TaskStatusUpdateEvent,
    TextPart,
)
from a2a.utils import new_agent_text_message, new_task
from a2a.utils.parts import get_file_parts

from app.agent import CopilotConceptAgent
from app.models import UploadedFile


class CopilotConceptExecutor(AgentExecutor):
    def __init__(self) -> None:
        self._agent = CopilotConceptAgent()

    @override
    async def execute(
        self,
        context: RequestContext,
        event_queue: EventQueue,
    ) -> None:
        if not context.message:
            raise ValueError('No message provided')

        task = context.current_task or new_task(context.message)
        if not context.current_task:
            await event_queue.enqueue_event(task)

        await event_queue.enqueue_event(
            TaskStatusUpdateEvent(
                status=TaskStatus(
                    state=TaskState.working,
                    message=new_agent_text_message(
                        'Processing the A2A request and building a repository-specific guide.',
                        task.context_id,
                        task.id,
                    ),
                ),
                final=False,
                contextId=task.context_id,
                taskId=task.id,
            )
        )

        headers = {}
        if context.call_context:
            headers = context.call_context.state.get('headers', {}) or {}

        uploads = self._extract_uploads(context)
        reply = await self._agent.reply(
            context.get_user_input(),
            uploads,
            headers.get('authorization') or headers.get('Authorization'),
        )
        artifact = self._build_artifact(reply.content, reply.files)

        await event_queue.enqueue_event(
            TaskArtifactUpdateEvent(
                append=False,
                artifact=artifact,
                lastChunk=True,
                contextId=task.context_id,
                taskId=task.id,
            )
        )
        await event_queue.enqueue_event(
            TaskStatusUpdateEvent(
                status=TaskStatus(state=TaskState.completed),
                final=True,
                contextId=task.context_id,
                taskId=task.id,
            )
        )

    @override
    async def cancel(
        self,
        context: RequestContext,
        event_queue: EventQueue,
    ) -> None:
        raise ValueError('cancel not supported')

    def _extract_uploads(self, context: RequestContext) -> list[UploadedFile]:
        uploads = []
        for file_obj in get_file_parts(context.message.parts if context.message else []):
            if isinstance(file_obj, FileWithBytes) and file_obj.bytes:
                uploads.append(
                    UploadedFile(
                        name=file_obj.name or 'attachment',
                        mime_type=file_obj.mime_type or 'application/octet-stream',
                        bytes_base64=file_obj.bytes,
                    )
                )
        return uploads

    def _build_artifact(
        self,
        content: str,
        files: list,
    ) -> Artifact:
        parts = [Part(TextPart(kind='text', text=content))]
        for file_info in files:
            parts.append(
                Part(
                    FilePart(
                        file=FileWithBytes(
                            bytes=file_info.bytes_base64,
                            mime_type=file_info.mime_type,
                            name=file_info.name,
                        )
                    )
                )
            )
        return Artifact(
            artifact_id=uuid4().hex,
            name='copilot-customization-response',
            description='A2A response from the Copilot customization guide agent',
            parts=parts,
        )
