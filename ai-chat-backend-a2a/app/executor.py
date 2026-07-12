from __future__ import annotations

import json
import logging
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

logger = logging.getLogger(__name__)

# Field names that may carry large base64-encoded binary payloads and must
# be redacted before a model is dumped to the logs.
_BINARY_FIELD_NAMES = {'bytes', 'content_base64', 'bytes_base64'}


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

        self._log_a2a_payload('a2a.request.payload', context.message)

        task = context.current_task or new_task(context.message)
        if not context.current_task:
            self._log_a2a_payload('a2a.stream.payload', task)
            await event_queue.enqueue_event(task)

        initial_status = TaskStatusUpdateEvent(
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
        self._log_a2a_payload('a2a.stream.payload', initial_status)
        await event_queue.enqueue_event(initial_status)

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
        self._log_a2a_payload('a2a.response.payload', artifact)

        artifact_update = TaskArtifactUpdateEvent(
            append=False,
            artifact=artifact,
            lastChunk=True,
            contextId=task.context_id,
            taskId=task.id,
        )
        self._log_a2a_payload('a2a.stream.payload', artifact_update)
        await event_queue.enqueue_event(artifact_update)

        completed_status = TaskStatusUpdateEvent(
            status=TaskStatus(state=TaskState.completed),
            final=True,
            contextId=task.context_id,
            taskId=task.id,
        )
        self._log_a2a_payload('a2a.stream.payload', completed_status)
        await event_queue.enqueue_event(completed_status)

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

    def _redact_binary_fields(self, value):
        """Recursively redact base64/bytes fields so raw payload logs stay
        small and never leak large binary content into the log stream."""
        if isinstance(value, dict):
            redacted = {}
            for field_name, field_value in value.items():
                if field_name in _BINARY_FIELD_NAMES and isinstance(field_value, str):
                    redacted[field_name] = {
                        'redacted': True,
                        'length': len(field_value),
                    }
                else:
                    redacted[field_name] = self._redact_binary_fields(field_value)
            return redacted
        if isinstance(value, list):
            return [self._redact_binary_fields(item) for item in value]
        return value

    def _log_a2a_payload(self, key: str, model) -> None:
        """Log the raw, bytes-redacted A2A wire payload for a protocol
        model (request message, task, status/artifact update event, etc.)."""
        logger.info(
            '%s %s',
            key,
            json.dumps(
                self._redact_binary_fields(model.model_dump(mode='json', exclude_none=True))
            ),
        )
