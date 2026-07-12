from __future__ import annotations

import hashlib
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
from app.models import AgentReply, UploadedFile


logger = logging.getLogger(__name__)
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
            await self._enqueue_event(task, event_queue)

        await self._enqueue_event(
            TaskStatusUpdateEvent(
                status=TaskStatus(
                    state=TaskState.working,
                    message=new_agent_text_message(
                        'Request received. Starting the Strands agent workflow.',
                        task.context_id,
                        task.id,
                    ),
                ),
                final=False,
                contextId=task.context_id,
                taskId=task.id,
            ),
            event_queue,
        )

        headers = {}
        if context.call_context:
            headers = context.call_context.state.get('headers', {}) or {}

        uploads = self._extract_uploads(context)
        user_input = context.get_user_input()
        logger.info(
            'a2a.request %s',
            json.dumps(
                {
                    'task_id': task.id,
                    'context_id': task.context_id,
                    'user_input_length': len(user_input),
                    'uploads': [
                        {
                            'name_fingerprint': self._fingerprint_text(upload.name),
                            'mime_type': upload.mime_type,
                            'bytes_base64_length': len(upload.bytes_base64),
                        }
                        for upload in uploads
                    ],
                }
            ),
        )
        if logger.isEnabledFor(logging.DEBUG):
            logger.debug(
                'a2a.request.payload %s',
                json.dumps(
                    {
                        'task_id': task.id,
                        'context_id': task.context_id,
                        'user_input_fingerprint': self._fingerprint_text(user_input),
                    }
                ),
            )

        reply = await self._stream_agent_reply(
            user_input,
            uploads,
            headers.get('authorization') or headers.get('Authorization'),
            task.id,
            task.context_id,
            event_queue,
        )
        self._log_a2a_payload(
            'a2a.response.payload',
            self._build_artifact(reply.content, reply.files),
        )
        logger.info(
            'a2a.response %s',
            json.dumps(
                {
                    'task_id': task.id,
                    'context_id': task.context_id,
                    'response_text_length': len(reply.content),
                    'files': [
                        {
                            'name_fingerprint': self._fingerprint_text(file_info.name),
                            'mime_type': file_info.mime_type,
                            'bytes_base64_length': len(file_info.bytes_base64),
                        }
                        for file_info in reply.files
                    ],
                }
            ),
        )
        if logger.isEnabledFor(logging.DEBUG):
            logger.debug(
                'a2a.response.payload %s',
                json.dumps(
                    {
                        'task_id': task.id,
                        'context_id': task.context_id,
                        'response_text_fingerprint': self._fingerprint_text(reply.content),
                    }
                ),
            )

        await self._enqueue_event(
            TaskStatusUpdateEvent(
                status=TaskStatus(state=TaskState.completed),
                final=True,
                contextId=task.context_id,
                taskId=task.id,
            ),
            event_queue,
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
            name='strands-agent-response',
            description='A2A response from the Strands agent',
            parts=parts,
        )

    async def _stream_agent_reply(
        self,
        user_input: str,
        uploads: list[UploadedFile],
        authorization_header: str | None,
        task_id: str,
        context_id: str,
        event_queue: EventQueue,
    ) -> AgentReply:
        text_artifact_id = uuid4().hex
        final_reply: AgentReply | None = None
        has_streamed_text = False

        async for stream_event in self._agent.stream_reply(
            user_input,
            uploads,
            authorization_header,
            task_id,
        ):
            if stream_event.status_text:
                await self._enqueue_event(
                    TaskStatusUpdateEvent(
                        status=TaskStatus(
                            state=TaskState.working,
                            message=new_agent_text_message(
                                stream_event.status_text,
                                context_id,
                                task_id,
                            ),
                        ),
                        final=False,
                        contextId=context_id,
                        taskId=task_id,
                    ),
                    event_queue,
                )

            if stream_event.text_chunk:
                await self._enqueue_event(
                    TaskArtifactUpdateEvent(
                        append=has_streamed_text,
                        artifact=self._build_text_artifact(
                            stream_event.text_chunk,
                            text_artifact_id,
                        ),
                        lastChunk=False,
                        contextId=context_id,
                        taskId=task_id,
                    ),
                    event_queue,
                )
                has_streamed_text = True

            if stream_event.final_reply:
                final_reply = stream_event.final_reply

        if not final_reply:
            raise ValueError('Strands agent completed without a final reply')

        await self._enqueue_event(
            TaskArtifactUpdateEvent(
                append=False,
                artifact=self._build_text_artifact(
                    final_reply.content,
                    text_artifact_id,
                ),
                lastChunk=not final_reply.files,
                contextId=context_id,
                taskId=task_id,
            ),
            event_queue,
        )

        for index, file_info in enumerate(final_reply.files):
            await self._enqueue_event(
                TaskArtifactUpdateEvent(
                    append=False,
                    artifact=Artifact(
                        artifact_id=uuid4().hex,
                        name=file_info.name,
                        description='A2A file response from the Strands agent',
                        parts=[
                            Part(
                                FilePart(
                                    file=FileWithBytes(
                                        bytes=file_info.bytes_base64,
                                        mime_type=file_info.mime_type,
                                        name=file_info.name,
                                    )
                                )
                            )
                        ],
                    ),
                    lastChunk=index == len(final_reply.files) - 1,
                    contextId=context_id,
                    taskId=task_id,
                ),
                event_queue,
            )

        return final_reply

    def _build_text_artifact(self, content: str, artifact_id: str) -> Artifact:
        return Artifact(
            artifact_id=artifact_id,
            name='strands-agent-response',
            description='A2A response from the Strands agent',
            parts=[Part(TextPart(kind='text', text=content))],
        )

    async def _enqueue_event(self, event, event_queue: EventQueue) -> None:
        self._log_a2a_payload('a2a.stream.payload', event)
        await event_queue.enqueue_event(event)

    def _redact_binary_fields(self, value):
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
        logger.info(
            '%s %s',
            key,
            json.dumps(
                self._redact_binary_fields(
                    model.model_dump(mode='json', exclude_none=True)
                )
            ),
        )

    def _fingerprint_text(self, text: str | None) -> dict[str, str | int]:
        normalized = text or ''
        return {
            'length': len(normalized),
            'sha256': hashlib.sha256(normalized.encode('utf-8')).hexdigest(),
        }
