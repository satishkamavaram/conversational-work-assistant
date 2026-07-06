const A2A_BASE_URL = process.env.REACT_APP_A2A_SERVER_URL || '';

const createRequestId = () => {
  if (typeof crypto !== 'undefined' && crypto.randomUUID) {
    return crypto.randomUUID();
  }
  return `${Date.now()}-${Math.random().toString(16).slice(2)}`;
};

const buildTextPart = (message) => ({
  kind: 'text',
  text: message,
});

const buildFilePart = (file) => ({
  kind: 'file',
  file: {
    name: file.name,
    mimeType: file.mime_type,
    bytes: file.bytes,
  },
});

export const buildSendMessageRequest = ({ message, upload_files = [] }, session) => ({
  jsonrpc: '2.0',
  id: createRequestId(),
  method: 'message/send',
  params: {
    message: {
      kind: 'message',
      messageId: createRequestId(),
      role: 'user',
      contextId: session.contextId || undefined,
      taskId: session.taskId || undefined,
      parts: [
        ...(message ? [buildTextPart(message)] : []),
        ...upload_files.map(buildFilePart),
      ],
    },
    configuration: {
      blocking: true,
    },
  },
});

export const fetchAgentCard = async (token) => {
  const response = await fetch(`${A2A_BASE_URL}/.well-known/agent-card.json`, {
    headers: token ? { Authorization: `Bearer ${token}` } : {},
  });

  if (!response.ok) {
    throw new Error(`Agent card request failed with ${response.status}`);
  }

  return response.json();
};

export const sendA2AMessage = async (payload, session, token) => {
  const response = await fetch(`${A2A_BASE_URL}/`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
    },
    body: JSON.stringify(buildSendMessageRequest(payload, session)),
  });

  if (!response.ok) {
    throw new Error(`A2A request failed with ${response.status}`);
  }

  return response.json();
};

const extractTextFromParts = (parts = []) =>
  parts
    .filter((part) => part.kind === 'text' && part.text)
    .map((part) => part.text)
    .join('\n')
    .trim();

const extractFilesFromParts = (parts = []) =>
  parts
    .filter((part) => part.kind === 'file' && part.file)
    .map((part) => ({
      name: part.file.name,
      mime_type: part.file.mimeType || part.file.mime_type,
      bytes: part.file.bytes,
    }));

const extractAssistantArtifact = (task) => {
  const artifacts = task?.artifacts || [];
  return artifacts.length > 0 ? artifacts[artifacts.length - 1] : null;
};

export const normalizeA2AResponse = (response) => {
  if (response.error) {
    throw new Error(response.error.message || 'A2A request failed');
  }

  const result = response.result;

  if (!result) {
    return {
      content: 'The A2A agent returned an empty response.',
      files: [],
      contextId: null,
      taskId: null,
    };
  }

  if (result.kind === 'message') {
    return {
      content: extractTextFromParts(result.parts),
      files: extractFilesFromParts(result.parts),
      contextId: result.contextId || result.context_id || null,
      taskId: result.taskId || result.task_id || null,
    };
  }

  if (result.kind === 'task') {
    const artifact = extractAssistantArtifact(result);
    const artifactParts = artifact?.parts || [];
    const fallbackParts = result.status?.message?.parts || [];

    return {
      content:
        extractTextFromParts(artifactParts) ||
        extractTextFromParts(fallbackParts) ||
        'The task completed without a text response.',
      files: extractFilesFromParts(artifactParts),
      contextId: result.contextId || result.context_id || null,
      taskId: result.id || null,
    };
  }

  return {
    content: 'Received an unsupported A2A response shape.',
    files: [],
    contextId: null,
    taskId: null,
  };
};
