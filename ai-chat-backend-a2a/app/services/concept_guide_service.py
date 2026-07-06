from __future__ import annotations

import base64

from app.knowledge_base import COPILOT_CONCEPTS, WORKFLOW_GUIDANCE
from app.models import AgentReply, GeneratedFile, UploadedFile
from app.services.attachment_service import AttachmentService


class ConceptGuideService:
    def __init__(self) -> None:
        self._attachments = AttachmentService()

    def reply(self, query: str, uploads: list[UploadedFile]) -> AgentReply:
        normalized_query = (query or '').strip()
        requested_topics = self._match_topics(normalized_query)

        sections = [
            'This backend is an A2A guide agent for the paired frontend/backend setup.',
            self._build_topic_section(requested_topics),
            self._build_workflow_section(),
            self._attachments.summarize(uploads),
        ]
        content = '\n\n'.join(section for section in sections if section)

        files = []
        if self._should_export_guide(normalized_query):
            files.append(self._build_study_guide(content, requested_topics))

        return AgentReply(content=content, files=files)

    def _match_topics(self, query: str) -> list[str]:
        lowered = query.lower()
        matched = [
            topic
            for topic in COPILOT_CONCEPTS
            if topic in lowered
        ]
        return matched or list(COPILOT_CONCEPTS.keys())

    def _build_topic_section(self, topics: list[str]) -> str:
        sections = []
        for topic in topics:
            details = COPILOT_CONCEPTS[topic]
            sections.append(
                '\n'.join(
                    [
                        topic.title(),
                        f"- Scope: {details['scope']}",
                        f"- Invocation: {details['invocation']}",
                        f"- Best for: {details['best_for']}",
                        f"- Applied here: {details['applied_here']}",
                    ]
                )
            )
        return '\n\n'.join(sections)

    def _build_workflow_section(self) -> str:
        return 'Recommended rollout:\n' + '\n'.join(
            f"{index}. {item}" for index, item in enumerate(WORKFLOW_GUIDANCE, start=1)
        )

    def _should_export_guide(self, query: str) -> bool:
        lowered = query.lower()
        return 'export' in lowered or 'download' in lowered or 'study guide' in lowered

    def _build_study_guide(self, content: str, topics: list[str]) -> GeneratedFile:
        title = '# Copilot customization study guide\n\n'
        topic_line = 'Topics: ' + ', '.join(topic.title() for topic in topics) + '\n\n'
        markdown = title + topic_line + content + '\n'
        encoded = base64.b64encode(markdown.encode('utf-8')).decode('utf-8')
        return GeneratedFile(
            name='copilot-customization-study-guide.md',
            mime_type='text/markdown',
            bytes_base64=encoded,
        )
