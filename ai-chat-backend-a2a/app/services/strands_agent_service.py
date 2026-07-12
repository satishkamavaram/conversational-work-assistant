from __future__ import annotations

import hashlib
import json
import logging
import time
import uuid
from collections.abc import AsyncIterator
from typing import TYPE_CHECKING, Any
from urllib.parse import urlsplit, urlunsplit

from app.config import settings
from app.models import AgentReply, AgentStreamEvent, GeneratedFile, UploadedFile
from app.services.strands_result_parser import (
    extract_generated_file_names,
    extract_token_usage,
    extract_tool_calls,
    extract_tool_results,
    has_tool_results,
)

if TYPE_CHECKING:
    from strands import Agent
    from strands.models.litellm import LiteLLMModel
    from strands.tools.mcp.mcp_client import MCPClient


logger = logging.getLogger(__name__)


class StrandsAgentService:
    _INTERNAL_ONLY_TOOLS = {
        'download_cv_document',
        'fetch_files_content',
        'save_uploaded_files',
    }

    def __init__(self) -> None:
        self._ensure_required_settings()
        self.model = self._build_model()

    async def reply(
        self,
        query: str,
        uploads: list[UploadedFile],
        authorization_header: str | None = None,
        trace_session_id: str | None = None,
    ) -> AgentReply:
        final_reply: AgentReply | None = None
        async for event in self.stream_reply(
            query,
            uploads,
            authorization_header,
            trace_session_id,
        ):
            if event.final_reply:
                final_reply = event.final_reply

        if not final_reply:
            raise ValueError('Strands agent completed without a final reply')

        return final_reply

    async def stream_reply(
        self,
        query: str,
        uploads: list[UploadedFile],
        authorization_header: str | None = None,
        trace_session_id: str | None = None,
    ) -> AsyncIterator[AgentStreamEvent]:
        logger.info(
            'strands.request.start %s',
            json.dumps(
                {
                    'model_id': settings.strands_model_id,
                    'mcp_server_url': self._sanitize_url(settings.mcp_server_url),
                    'input': self._build_input_summary(query, uploads),
                    'authorization_header_present': bool(authorization_header),
                }
            ),
        )
        if logger.isEnabledFor(logging.DEBUG):
            logger.debug(
                'strands.request.payload %s',
                json.dumps(
                    {
                        'text_fingerprint': self._fingerprint_text(query),
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
        client = self._build_mcp_client(authorization_header)
        started_at = time.perf_counter()
        active_client = self._enter_client(client)
        try:
            yield AgentStreamEvent(
                status_text='MCP connection established. Discovering available tools.'
            )
            tools = self._get_exposed_tools(active_client)
            yield AgentStreamEvent(
                status_text=(
                    f'MCP tool discovery complete. Received {len(tools)} tool(s): '
                    f'{self._format_tool_names(tools)}'
                )
            )
            agent = self._build_agent(tools, authorization_header, trace_session_id)
            yield AgentStreamEvent(
                status_text=(
                    f'Agent created with model {settings.strands_model_id} '
                    f'and {len(tools)} tool(s)'
                )
            )

            response_chunks: list[str] = []
            token_usage = {
                'input_tokens': 0,
                'output_tokens': 0,
                'total_tokens': 0,
            }
            requested_files: list[str] = []
            upload_requested = False
            llm_call_count = 1
            tool_calls: list[dict[str, Any]] = []
            pending_tool_calls: dict[str, dict[str, Any]] = {}
            awaiting_llm_response = True
            pending_llm_call_announcement = False

            yield AgentStreamEvent(
                status_text=(
                    f'LLM model call invoked with model {settings.strands_model_id} '
                    f'(turn {llm_call_count})'
                )
            )

            async for event in agent.stream_async(query):
                if pending_llm_call_announcement:
                    yield AgentStreamEvent(
                        status_text=(
                            f'LLM model call invoked with model {settings.strands_model_id} '
                            f'(turn {llm_call_count})'
                        )
                    )
                    pending_llm_call_announcement = False

                event_tool_calls = extract_tool_calls(event)
                if event_tool_calls and awaiting_llm_response:
                    yield AgentStreamEvent(
                        status_text=(
                            f'Received LLM model response from {settings.strands_model_id} '
                            f'(turn {llm_call_count})'
                        )
                    )
                    awaiting_llm_response = False

                for tool_call in event_tool_calls:
                    tool_use_id = tool_call.get('tool_use_id') or uuid.uuid4().hex
                    tool_name = tool_call.get('name')
                    tool_input = tool_call.get('input') or {}
                    if tool_name == 'get_cv_document':
                        requested_files.append('__cv__')
                    elif tool_name == 'download_files':
                        names = tool_input.get('filenames') or []
                        if isinstance(names, str):
                            names = [names]
                        requested_files.extend(names)
                    elif tool_name == 'upload_files':
                        upload_requested = True

                    tool_calls.append(
                        {
                            'tool_use_id': tool_use_id,
                            'name': tool_name or '<unknown>',
                            'input': self._sanitize_for_log(tool_input),
                        }
                    )
                    pending_tool_calls[tool_use_id] = {
                        'name': tool_name or '<unknown>',
                        'input': tool_input,
                    }
                    yield AgentStreamEvent(
                        status_text=(
                            f"Tool call -> {tool_name or 'unknown'} "
                            f"with arguments {self._format_event_payload(tool_input)}"
                        )
                    )

                output_chunk = event['data'] if isinstance(event.get('data'), str) else ''
                if output_chunk:
                    if awaiting_llm_response:
                        yield AgentStreamEvent(
                            status_text=(
                                f'Received LLM model response from '
                                f'{settings.strands_model_id} (turn {llm_call_count})'
                            )
                        )
                        awaiting_llm_response = False
                    response_chunks.append(output_chunk)
                    yield AgentStreamEvent(text_chunk=output_chunk)

                event_token_usage = extract_token_usage(event)
                for key, value in event_token_usage.items():
                    token_usage[key] = max(token_usage[key], value)

                requested_files.extend(extract_generated_file_names(event))
                if has_tool_results(event):
                    for tool_result in extract_tool_results(event):
                        yield AgentStreamEvent(
                            status_text=self._format_tool_result_event(
                                tool_result,
                                pending_tool_calls,
                            )
                        )
                    llm_call_count += 1
                    awaiting_llm_response = True
                    pending_llm_call_announcement = True

                logger.debug(
                    'strands.agent.turn %s',
                    json.dumps(
                        {
                            'turn': llm_call_count,
                            'tool_names': [
                                tool_call.get('name', '<unknown>')
                                for tool_call in event_tool_calls
                            ],
                            'output_length': len(output_chunk),
                            'token_usage': event_token_usage,
                        }
                    ),
                )
                if (event_tool_calls or output_chunk) and logger.isEnabledFor(logging.DEBUG):
                    logger.debug(
                        'strands.agent.turn.payload %s',
                        json.dumps(
                            {
                                'turn': llm_call_count,
                                'tool_calls': tool_calls[-len(event_tool_calls):] if event_tool_calls else [],
                                'output_fingerprint': self._fingerprint_text(output_chunk),
                            }
                        ),
                    )

            deduped_files: list[str] = []
            for name in requested_files:
                if name not in deduped_files:
                    deduped_files.append(name)

            full_response = ''.join(response_chunks).strip()
            delivered_files: list[GeneratedFile] = []
            if deduped_files:
                yield AgentStreamEvent(
                    status_text=(
                        f'Preparing {len(deduped_files)} file attachment(s) '
                        'with internal MCP file fetch tools'
                    )
                )
                delivered_files.extend(
                    self._fetch_named_files(active_client, deduped_files)
                )

            if upload_requested and uploads:
                yield AgentStreamEvent(
                    status_text='Tool call -> save_uploaded_files with uploaded file metadata'
                )
                save_result = self._save_uploaded_files(active_client, uploads)
                yield AgentStreamEvent(
                    status_text=(
                        'Tool response -> save_uploaded_files '
                        f'(status: success) -> {self._format_event_payload(save_result)}'
                    )
                )
                saved = save_result.get('saved', [])
                errors = save_result.get('errors', [])
                if saved:
                    saved_names = ', '.join(entry['filename'] for entry in saved)
                    full_response += f'\n\nFiles saved to server: {saved_names}'
                if errors:
                    failed_names = ', '.join(
                        entry.get('filename', '?') if isinstance(entry, dict) else str(entry)
                        for entry in errors
                    )
                    full_response += f'\n\nFailed to save: {failed_names}'

            elapsed_ms = round((time.perf_counter() - started_at) * 1000)
            yield AgentStreamEvent(
                status_text=(
                    'Final response ready. '
                    f'model={settings.strands_model_id}, '
                    f'llm_calls={llm_call_count}, '
                    f'input_tokens={token_usage["input_tokens"]}, '
                    f'output_tokens={token_usage["output_tokens"]}, '
                    f'total_tokens={token_usage["total_tokens"]}, '
                    f'elapsed_ms={elapsed_ms}'
                )
            )
            logger.info(
                'strands.request.complete %s',
                json.dumps(
                    {
                        'model_id': settings.strands_model_id,
                        'total_turns': llm_call_count,
                        'elapsed_ms': elapsed_ms,
                        'token_usage': token_usage,
                        'tool_call_count': len(tool_calls),
                        'tool_call_names': [
                            call.get('name', '<unknown>')
                            for call in tool_calls
                        ],
                        'requested_file_count': len(deduped_files),
                        'requested_file_fingerprints': [
                            self._fingerprint_text(name)
                            for name in deduped_files
                        ],
                        'upload_requested': upload_requested,
                        'response': self._build_response_summary(
                            full_response,
                            delivered_files,
                        ),
                    }
                ),
            )
            yield AgentStreamEvent(
                final_reply=AgentReply(content=full_response, files=delivered_files)
            )
        finally:
            self._exit_client(client)

    def _ensure_required_settings(self) -> None:
        if not settings.openai_api_key:
            raise ValueError('OPENAI_API_KEY is required')
        if not settings.mcp_server_url:
            raise ValueError('MCP_SERVER_URL is required')

    def _build_model(self) -> LiteLLMModel:
        try:
            from strands.models.litellm import LiteLLMModel
        except ImportError as exc:
            raise RuntimeError(
                'Strands dependencies are not installed. Install requirements.txt.'
            ) from exc

        return LiteLLMModel(
            client_args={
                'api_key': settings.openai_api_key,
                'base_url': None,
            },
            model_id=settings.strands_model_id,
            params={'temperature': 1.0},
        )

    def _build_agent(
        self,
        tools: list[Any],
        authorization_header: str | None = None,
        trace_session_id: str | None = None,
    ) -> Agent:
        try:
            from strands import Agent
        except ImportError as exc:
            raise RuntimeError(
                'Strands dependencies are not installed. Install requirements.txt.'
            ) from exc

        system_prompt = """
You are a Strands-based A2A assistant for this repository.

- Use MCP tools when they are relevant to the user's request.
- For CV or document download requests, call get_cv_document or download_files.
- For file upload or save requests, call upload_files.
- For generated documents or presentations, confirm briefly that the file is ready.
- Keep answers concise and factual.
""".strip()

        return Agent(
            model=self.model,
            tools=tools,
            system_prompt=system_prompt,
            callback_handler=None,
            trace_attributes=self._build_trace_attributes(
                authorization_header,
                trace_session_id,
            ),
        )

    def _build_trace_attributes(
        self,
        authorization_header: str | None,
        trace_session_id: str | None,
    ) -> dict[str, str | list[str]]:
        _ = authorization_header
        return {
            'session.id': trace_session_id or uuid.uuid4().hex,
            'langfuse.tags': [
                'Agent-SDK-Example',
                'Strands-Project-Demo',
                'Observability-Tutorial',
            ],
        }

    def _build_mcp_client(self, authorization_header: str | None) -> MCPClient:
        try:
            from mcp.client.streamable_http import streamablehttp_client
            from strands.tools.mcp.mcp_client import MCPClient
        except ImportError as exc:
            raise RuntimeError(
                'MCP/Strands client dependencies are not installed. Install requirements.txt.'
            ) from exc

        headers = {}
        if authorization_header:
            headers['Authorization'] = authorization_header

        return MCPClient(
            lambda: streamablehttp_client(
                url=settings.mcp_server_url,
                headers=headers,
            )
        )

    def _enter_client(self, client):
        entered_client = client.__enter__()
        return entered_client or client

    def _exit_client(self, client) -> None:
        exit_method = getattr(client, '__exit__', None)
        if callable(exit_method):
            exit_method(None, None, None)

    def _get_exposed_tools(self, client) -> list:
        all_tools = client.list_tools_sync()
        exposed_tools = [
            tool
            for tool in all_tools
            if getattr(tool, 'tool_name', None) not in self._INTERNAL_ONLY_TOOLS
        ]
        logger.info(
            'strands.tools.available %s',
            json.dumps(
                {
                    'tool_count': len(exposed_tools),
                    'tool_names': [
                        getattr(tool, 'tool_name', '<unknown>')
                        for tool in exposed_tools
                    ]
                }
            ),
        )
        return exposed_tools

    def _fetch_named_files(self, client, requested_files: list[str]) -> list[GeneratedFile]:
        generated_files = []
        if '__cv__' in requested_files:
            generated_files.append(self._fetch_cv_file(client))

        named_files = [name for name in requested_files if name != '__cv__']
        if named_files:
            generated_files.extend(self._fetch_files_content(client, named_files))
        return generated_files

    def _fetch_cv_file(self, client) -> GeneratedFile:
        payload = self._call_json_tool(client, 'download_cv_document')
        bytes_base64 = payload.get('content_base64')
        if not bytes_base64:
            raise ValueError(
                'download_cv_document returned no content_base64 payload'
            )
        return GeneratedFile(
            name=payload.get('filename', 'document'),
            mime_type=payload.get('mime_type', 'application/octet-stream'),
            bytes_base64=bytes_base64,
        )

    def _fetch_files_content(self, client, filenames: list[str]) -> list[GeneratedFile]:
        payload = self._call_json_tool(
            client,
            'fetch_files_content',
            arguments={'filenames': filenames},
        )
        files = []
        for entry in payload.get('files', []):
            bytes_base64 = entry.get('content_base64')
            if not bytes_base64:
                raise ValueError(
                    f"fetch_files_content returned no content_base64 for {entry.get('filename', 'document')}"
                )
            files.append(
                GeneratedFile(
                    name=entry.get('filename', 'document'),
                    mime_type=entry.get('mime_type', 'application/octet-stream'),
                    bytes_base64=bytes_base64,
                )
            )
        return files

    def _save_uploaded_files(self, client, uploads: list[UploadedFile]) -> dict:
        files = [
            {
                'filename': upload.name,
                'mime_type': upload.mime_type,
                'content_base64': upload.bytes_base64,
            }
            for upload in uploads
        ]
        if not files:
            return {'saved': [], 'errors': []}
        return self._call_json_tool(
            client,
            'save_uploaded_files',
            arguments={'files': files},
        )

    def _call_json_tool(
        self,
        client,
        tool_name: str,
        arguments: dict | None = None,
    ) -> dict:
        logger.info(
            'strands.tool.call %s',
            json.dumps(
                {
                    'tool_name': tool_name,
                    'has_arguments': bool(arguments),
                }
            ),
        )
        if arguments and logger.isEnabledFor(logging.DEBUG):
            logger.debug(
                'strands.tool.call.payload %s',
                json.dumps(
                    {
                        'tool_name': tool_name,
                        'arguments': self._sanitize_for_log(arguments),
                    }
                ),
            )
        result = client.call_tool_sync(
            tool_use_id=uuid.uuid4().hex,
            name=tool_name,
            arguments=arguments,
        )

        if isinstance(result, dict):
            structured = result.get('structuredContent')
            if isinstance(structured, dict):
                logger.info(
                    'strands.tool.result %s',
                    json.dumps(
                        {
                            'tool_name': tool_name,
                            'keys': sorted(structured.keys()),
                        }
                    ),
                )
                if logger.isEnabledFor(logging.DEBUG):
                    logger.debug(
                        'strands.tool.result.payload %s',
                        json.dumps(
                            {
                                'tool_name': tool_name,
                                'result': self._sanitize_for_log(structured),
                            }
                        ),
                    )
                return structured
            content = result.get('content') or []
        else:
            structured = getattr(result, 'structuredContent', None)
            if isinstance(structured, dict):
                logger.info(
                    'strands.tool.result %s',
                    json.dumps(
                        {
                            'tool_name': tool_name,
                            'keys': sorted(structured.keys()),
                        }
                    ),
                )
                if logger.isEnabledFor(logging.DEBUG):
                    logger.debug(
                        'strands.tool.result.payload %s',
                        json.dumps(
                            {
                                'tool_name': tool_name,
                                'result': self._sanitize_for_log(structured),
                            }
                        ),
                    )
                return structured
            content = getattr(result, 'content', []) or []

        for block in content:
            text = block.get('text') if isinstance(block, dict) else getattr(block, 'text', None)
            if not text:
                continue
            try:
                parsed = json.loads(text)
                if isinstance(parsed, dict):
                    logger.info(
                        'strands.tool.result %s',
                        json.dumps(
                            {
                                'tool_name': tool_name,
                                'keys': sorted(parsed.keys()),
                            }
                        ),
                    )
                    if logger.isEnabledFor(logging.DEBUG):
                        logger.debug(
                            'strands.tool.result.payload %s',
                            json.dumps(
                                {
                                    'tool_name': tool_name,
                                    'result': self._sanitize_for_log(parsed),
                                }
                            ),
                        )
                    return parsed
            except json.JSONDecodeError:
                continue

        raise ValueError(f'Tool {tool_name} did not return structured JSON content.')

    def _build_input_summary(
        self,
        query: str,
        uploads: list[UploadedFile],
    ) -> dict[str, Any]:
        return {
            'text_length': len(query),
            'upload_count': len(uploads),
            'uploads': [
                {
                    'name_fingerprint': self._fingerprint_text(upload.name),
                    'mime_type': upload.mime_type,
                    'bytes_base64_length': len(upload.bytes_base64),
                }
                for upload in uploads
            ],
        }

    def _build_response_summary(
        self,
        content: str,
        files: list[GeneratedFile],
    ) -> dict[str, Any]:
        return {
            'text_length': len(content),
            'file_count': len(files),
            'files': [
                {
                    'name_fingerprint': self._fingerprint_text(file_info.name),
                    'mime_type': file_info.mime_type,
                    'bytes_base64_length': len(file_info.bytes_base64),
                }
                for file_info in files
            ],
        }

    def _fingerprint_text(self, text: str | None) -> dict[str, str | int]:
        normalized = text or ''
        return {
            'length': len(normalized),
            'sha256': hashlib.sha256(normalized.encode('utf-8')).hexdigest(),
        }

    def _sanitize_for_log(
        self,
        value: Any,
        limit: int = 200,
        field_name: str | None = None,
    ) -> Any:
        if isinstance(value, dict):
            return {
                key: (
                    {'redacted': True, 'length': len(item)}
                    if key in {'content_base64', 'bytes', 'bytes_base64'}
                    and isinstance(item, str)
                    else self._sanitize_for_log(item, limit, key)
                )
                for key, item in value.items()
            }
        if isinstance(value, list):
            return [self._sanitize_for_log(item, limit, field_name) for item in value]
        if isinstance(value, str):
            if field_name in {'status', 'mime_type', 'content_type', 'tool_name'}:
                return value if len(value) <= limit else f'{value[:limit]}...'
            return {
                'length': len(value),
                'sha256': hashlib.sha256(value.encode('utf-8')).hexdigest(),
            }
        return value

    def _sanitize_url(self, value: str) -> str:
        parsed = urlsplit(value)
        return urlunsplit((parsed.scheme, parsed.netloc, parsed.path, '', ''))

    def _format_tool_result_event(
        self,
        tool_result: dict[str, Any],
        pending_tool_calls: dict[str, dict[str, Any]],
    ) -> str:
        tool_use_id = tool_result.get('tool_use_id')
        matched_call = pending_tool_calls.pop(tool_use_id, None) if tool_use_id else None
        tool_name = (
            matched_call.get('name')
            if matched_call
            else '<unknown>'
        )
        status = tool_result.get('status') or 'success'
        summary = self._summarize_tool_result(tool_result)
        return (
            f'Tool response -> {tool_name} '
            f'(status: {status}) -> {summary}'
        )

    def _summarize_tool_result(self, tool_result: dict[str, Any]) -> str:
        parsed_content = tool_result.get('content') or []
        if parsed_content:
            if len(parsed_content) == 1:
                return self._format_event_payload(parsed_content[0])
            return self._format_event_payload(parsed_content)

        text_content = tool_result.get('text') or []
        if text_content:
            if len(text_content) == 1:
                return self._format_event_text(text_content[0])
            return self._format_event_payload(text_content)

        return 'no structured payload returned'

    def _format_event_payload(self, value: Any) -> str:
        formatted = self._sanitize_for_event(value)
        return json.dumps(formatted, sort_keys=True)

    def _format_event_text(self, value: str, limit: int = 200) -> str:
        compact = ' '.join(value.split())
        if len(compact) <= limit:
            return compact
        return f'{compact[:limit]}...'

    def _sanitize_for_event(self, value: Any, depth: int = 0) -> Any:
        if depth >= 3:
            return '<truncated>'
        if isinstance(value, dict):
            return {
                key: (
                    {'redacted': True, 'length': len(item)}
                    if key in {'content_base64', 'bytes', 'bytes_base64'}
                    and isinstance(item, str)
                    else self._sanitize_for_event(item, depth + 1)
                )
                for key, item in value.items()
            }
        if isinstance(value, list):
            if len(value) > 10:
                return {
                    'count': len(value),
                    'items': [self._sanitize_for_event(item, depth + 1) for item in value[:3]],
                }
            return [self._sanitize_for_event(item, depth + 1) for item in value]
        if isinstance(value, str):
            return self._format_event_text(value, limit=120)
        return value

    def _format_tool_names(self, tools: list[Any], limit: int = 8) -> str:
        tool_names = [getattr(tool, 'tool_name', '<unknown>') for tool in tools]
        if len(tool_names) <= limit:
            return ', '.join(tool_names)
        head = ', '.join(tool_names[:limit])
        return f'{head}, ... (+{len(tool_names) - limit} more)'
