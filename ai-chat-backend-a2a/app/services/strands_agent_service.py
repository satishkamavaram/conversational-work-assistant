from __future__ import annotations

import json
import uuid

from app.config import settings
from app.models import AgentReply, GeneratedFile, UploadedFile
from app.services.strands_result_parser import (
    extract_generated_file_names,
    extract_tool_calls,
    extract_total_tokens,
)


class StrandsAgentService:
    _INTERNAL_ONLY_TOOLS = {
        'download_cv_document',
        'fetch_files_content',
        'save_uploaded_files',
    }

    def __init__(self) -> None:
        self._ensure_required_settings()

    async def reply(
        self,
        query: str,
        uploads: list[UploadedFile],
        authorization_header: str | None = None,
    ) -> AgentReply:
        client = self._build_mcp_client(authorization_header)
        client = self._enter_client(client)
        try:
            tools = self._get_exposed_tools(client)
            agent = self._build_agent(tools)
            full_response, total_tokens, requested_files, upload_requested = (
                await self._run_agent(agent, query)
            )

            delivered_files: list[GeneratedFile] = []
            if requested_files:
                delivered_files.extend(self._fetch_named_files(client, requested_files))

            if upload_requested and uploads:
                save_result = self._save_uploaded_files(client, uploads)
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

            full_response += f'\n\nTotal Tokens Consumed: {total_tokens}'
            return AgentReply(content=full_response, files=delivered_files)
        finally:
            self._exit_client(client)

    def _ensure_required_settings(self) -> None:
        if not settings.openai_api_key:
            raise ValueError(
                'OPENAI_API_KEY is required when A2A_AGENT_MODE=strands'
            )
        if not settings.mcp_server_url:
            raise ValueError(
                'MCP_SERVER_URL is required when A2A_AGENT_MODE=strands'
            )

    def _build_agent(self, tools: list):
        try:
            from strands import Agent
            from strands.models.litellm import LiteLLMModel
        except ImportError as exc:
            raise RuntimeError(
                'Strands dependencies are not installed. Install requirements.txt to use A2A_AGENT_MODE=strands.'
            ) from exc

        model = LiteLLMModel(
            client_args={
                'api_key': settings.openai_api_key,
                'base_url': None,
            },
            model_id=settings.strands_model_id,
            params={'temperature': 0.7},
        )

        system_prompt = """
You are a Strands-based A2A assistant for this repository.

- Use MCP tools when they are relevant to the user's request.
- For CV or document download requests, call get_cv_document or download_files.
- For file upload or save requests, call upload_files.
- For generated documents or presentations, confirm briefly that the file is ready.
- Keep answers concise and factual.
""".strip()

        return Agent(model=model, tools=tools, system_prompt=system_prompt)

    def _build_mcp_client(self, authorization_header: str | None):
        try:
            from mcp.client.streamable_http import streamablehttp_client
            from strands.tools.mcp.mcp_client import MCPClient
        except ImportError as exc:
            raise RuntimeError(
                'MCP/Strands client dependencies are not installed. Install requirements.txt to use A2A_AGENT_MODE=strands.'
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
        try:
            entered_client = client.__enter__()
            return entered_client or client
        except Exception:
            return client

    def _exit_client(self, client) -> None:
        exit_method = getattr(client, '__exit__', None)
        if callable(exit_method):
            exit_method(None, None, None)

    def _get_exposed_tools(self, client) -> list:
        all_tools = client.list_tools_sync()
        return [
            tool
            for tool in all_tools
            if getattr(tool, 'tool_name', None) not in self._INTERNAL_ONLY_TOOLS
        ]

    async def _run_agent(self, agent, query: str) -> tuple[str, int, list[str], bool]:
        response_chunks: list[str] = []
        total_tokens = 0
        requested_files: list[str] = []
        upload_requested = False

        async for event in agent.stream_async(query):
            for tool_call in extract_tool_calls(event):
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

            response_chunks.extend(
                [event['data']] if isinstance(event.get('data'), str) else []
            )
            total_tokens = max(total_tokens, extract_total_tokens(event))
            requested_files.extend(extract_generated_file_names(event))

        deduped_files = []
        for name in requested_files:
            if name not in deduped_files:
                deduped_files.append(name)
        return ''.join(response_chunks).strip(), total_tokens, deduped_files, upload_requested

    def _fetch_named_files(self, client, requested_files: list[str]) -> list[GeneratedFile]:
        generated_files = []
        if '__cv__' in requested_files:
            cv_file = self._fetch_cv_file(client)
            if cv_file:
                generated_files.append(cv_file)

        named_files = [name for name in requested_files if name != '__cv__']
        if named_files:
            generated_files.extend(self._fetch_files_content(client, named_files))
        return generated_files

    def _fetch_cv_file(self, client) -> GeneratedFile | None:
        payload = self._call_json_tool(client, 'download_cv_document')
        bytes_base64 = payload.get('content_base64')
        if not bytes_base64:
            return None
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
                continue
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
        result = client.call_tool_sync(
            tool_use_id=uuid.uuid4().hex,
            name=tool_name,
            arguments=arguments,
        )

        if isinstance(result, dict):
            structured = result.get('structuredContent')
            if isinstance(structured, dict):
                return structured
            content = result.get('content') or []
        else:
            structured = getattr(result, 'structuredContent', None)
            if isinstance(structured, dict):
                return structured
            content = getattr(result, 'content', []) or []

        for block in content:
            text = block.get('text') if isinstance(block, dict) else getattr(block, 'text', None)
            if not text:
                continue
            try:
                parsed = json.loads(text)
                if isinstance(parsed, dict):
                    return parsed
            except json.JSONDecodeError:
                continue

        raise ValueError(f'Tool {tool_name} did not return structured JSON content.')
