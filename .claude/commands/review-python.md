---
description: Review pending Python changes in backend/mcp against this repo's conventions
argument-hint: [optional focus, e.g. "mcp" or "layering"]
allowed-tools: Bash(git status:*), Bash(git diff:*)
---

## Current state

!`git status --short`

## Python diff

!`git diff -- '*.py'`

## Task

Review the diff above using the `python-code-reviewer` subagent. Pay special attention to: $ARGUMENTS

If the diff is empty, review `ai-chat-backend-a2a/app/` and `mcp/mcp_server.py` as they currently stand instead.
