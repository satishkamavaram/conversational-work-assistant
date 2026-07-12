from __future__ import annotations

import os
from dataclasses import dataclass
from dotenv import load_dotenv


load_dotenv()


@dataclass(frozen=True)
class Settings:
    host: str = os.getenv('A2A_HOST', '0.0.0.0')
    port: int = int(os.getenv('A2A_PORT', '8082'))
    public_base_url: str = os.getenv('A2A_PUBLIC_BASE_URL', 'http://localhost:8082')
    cors_origin: str = os.getenv('FRONTEND_ORIGIN', 'http://localhost:3000')
    openai_api_key: str = os.getenv('OPENAI_API_KEY', '')
    strands_model_id: str = os.getenv('STRANDS_MODEL_ID', 'openai/gpt-5-mini')
    mcp_server_url: str = os.getenv('MCP_SERVER_URL', 'http://127.0.0.1:8000/mcp')
    log_level: str = os.getenv('A2A_LOG_LEVEL', 'INFO')


settings = Settings()
