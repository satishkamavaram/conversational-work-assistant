COPILOT_CONCEPTS = {
    'custom instructions': {
        'scope': 'repository-wide',
        'invocation': 'automatic',
        'best_for': 'global standards, architecture rules, and validation commands',
        'applied_here': 'Both the frontend and backend repositories can keep A2A and Keycloak rules in .github/copilot-instructions.md so Copilot loads them on every task.',
    },
    'custom agents': {
        'scope': 'specialized persona or workflow',
        'invocation': 'manual or inferred',
        'best_for': 'separating implementer and reviewer responsibilities',
        'applied_here': 'A backend implementer agent can focus on the A2A contract while a reviewer agent checks task state handling, payload compatibility, and auth assumptions.',
    },
    'agent skills': {
        'scope': 'on-demand task knowledge',
        'invocation': 'automatic when relevant or explicit via slash command',
        'best_for': 'repeatable playbooks such as debugging A2A message payloads',
        'applied_here': 'A skill can bundle the exact checklist for agent-card verification, message/send payloads, task parsing, and attachment handling.',
    },
    'subagents': {
        'scope': 'runtime-only context isolation',
        'invocation': 'automatic delegation by the main agent',
        'best_for': 'deep tracing, focused reviews, and command execution without bloating the main conversation',
        'applied_here': 'One subagent can inspect the backend protocol, another can validate the frontend integration, and the main agent can keep the final implementation focused.',
    },
}

WORKFLOW_GUIDANCE = [
    'Start with repository custom instructions for always-on rules.',
    'Add custom agents when you want explicit handoffs such as implementer versus reviewer.',
    'Add skills when a task needs a reusable, targeted playbook.',
    'Let subagents handle large investigations or validation work in parallel.',
    'Once the code lives in GitHub, issue-to-branch and PR workflows become a natural next layer on top of these repository assets.',
]
