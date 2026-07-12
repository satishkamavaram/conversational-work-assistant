from __future__ import annotations

import json


def extract_token_usage(event: dict) -> dict[str, int]:
    usage = {
        'input_tokens': 0,
        'output_tokens': 0,
        'total_tokens': 0,
    }
    result = event.get('result')
    if not result or not hasattr(result, 'metrics'):
        return usage

    metrics = getattr(result, 'metrics', None)
    accumulated_usage = getattr(metrics, 'accumulated_usage', None)
    if not accumulated_usage:
        return usage

    usage['input_tokens'] = _read_token_value(
        accumulated_usage,
        'inputTokens',
        'input_tokens',
        'input',
    )
    usage['output_tokens'] = _read_token_value(
        accumulated_usage,
        'outputTokens',
        'output_tokens',
        'output',
    )
    usage['total_tokens'] = _read_token_value(
        accumulated_usage,
        'totalTokens',
        'total_tokens',
        'total',
    )
    return usage


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
                    'tool_use_id': tool_use.get('toolUseId') or tool_use.get('tool_use_id'),
                    'name': tool_use.get('name'),
                    'input': tool_use.get('input', {}),
                }
            )
    return tool_calls


def extract_tool_results(event: dict) -> list[dict]:
    tool_results = []
    message = event.get('message')
    if not isinstance(message, dict):
        return tool_results

    for item in message.get('content', []):
        if not isinstance(item, dict) or 'toolResult' not in item:
            continue

        tool_result = item['toolResult']
        parsed_content = []
        text_content = []
        for content_item in tool_result.get('content', []):
            payload = _parse_payload(content_item)
            if payload is not None:
                parsed_content.append(payload)
                continue
            text = _read_text(content_item)
            if text:
                text_content.append(text)

        tool_results.append(
            {
                'tool_use_id': tool_result.get('toolUseId') or tool_result.get('tool_use_id'),
                'status': tool_result.get('status'),
                'content': parsed_content,
                'text': text_content,
            }
        )

    return tool_results


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


def has_tool_results(event: dict) -> bool:
    message = event.get('message')
    if not isinstance(message, dict):
        return False

    for item in message.get('content', []):
        if isinstance(item, dict) and 'toolResult' in item:
            return True
    return False


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


def _read_token_value(usage: dict, *keys: str) -> int:
    for key in keys:
        value = usage.get(key)
        if isinstance(value, int):
            return value
    return 0


def _read_text(content_item: dict) -> str | None:
    if not isinstance(content_item, dict):
        return None
    text = content_item.get('text')
    return text if isinstance(text, str) else None
