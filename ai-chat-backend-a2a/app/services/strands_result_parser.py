from __future__ import annotations

import json


def extract_tool_calls(event: dict) -> list[dict]:
    tool_calls = []
    message = event.get('message')
    if not isinstance(message, dict):
        return tool_calls

    for content_item in message.get('content', []):
        if isinstance(content_item, dict) and 'toolUse' in content_item:
            tool_use = content_item['toolUse']
            tool_calls.append(
                {
                    'name': tool_use.get('name'),
                    'input': tool_use.get('input', {}),
                }
            )
    return tool_calls


def extract_generated_file_names(event: dict) -> list[str]:
    names = []
    message = event.get('message')
    if not isinstance(message, dict):
        return names

    for item in message.get('content', []):
        if not isinstance(item, dict) or 'toolResult' not in item:
            continue

        for content_item in item['toolResult'].get('content', []):
            payload = _parse_payload(content_item)
            if (
                isinstance(payload, dict)
                and payload.get('status') == 'created'
                and payload.get('filename')
            ):
                names.append(payload['filename'])
    return names


def extract_total_tokens(event: dict) -> int:
    result = event.get('result')
    if not result or not hasattr(result, 'metrics'):
        return 0

    metrics = getattr(result, 'metrics', None)
    usage = getattr(metrics, 'accumulated_usage', None)
    if not usage:
        return 0
    return usage.get('totalTokens', 0)


def _parse_payload(content_item: dict) -> dict | None:
    if not isinstance(content_item, dict):
        return None
    if 'json' in content_item and isinstance(content_item['json'], dict):
        return content_item['json']
    if 'text' in content_item:
        try:
            return json.loads(content_item['text'])
        except json.JSONDecodeError:
            return None
    return None
