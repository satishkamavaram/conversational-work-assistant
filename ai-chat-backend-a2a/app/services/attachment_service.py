from __future__ import annotations

import base64

from app.models import UploadedFile


class AttachmentService:
    def summarize(self, uploads: list[UploadedFile]) -> str:
        if not uploads:
            return 'No file attachments were included.'

        lines = ['Uploaded files:']
        for upload in uploads:
            size_bytes = self._decoded_size(upload.bytes_base64)
            lines.append(
                f"- {upload.name} ({upload.mime_type}, {size_bytes} bytes decoded)"
            )
        return '\n'.join(lines)

    @staticmethod
    def _decoded_size(bytes_base64: str) -> int:
        return len(base64.b64decode(bytes_base64.encode('utf-8')))
