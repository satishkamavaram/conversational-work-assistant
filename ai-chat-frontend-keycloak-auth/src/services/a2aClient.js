const DEFAULT_A2A_BASE_URL =
  process.env.NODE_ENV === 'development' ? 'http://localhost:8082' : '';

const A2A_BASE_URL = process.env.REACT_APP_A2A_SERVER_URL || DEFAULT_A2A_BASE_URL;

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

const buildMessagePayload = ({ message, upload_files = [] }, session) => ({
  kind: 'message',
  messageId: createRequestId(),
  role: 'user',
  contextId: session.contextId || undefined,
  taskId: session.taskId || undefined,
  parts: [
    ...(message ? [buildTextPart(message)] : []),
    ...upload_files.map(buildFilePart),
  ],
});

const buildRequest = ({ message, upload_files = [] }, session, method, configuration) => ({
  jsonrpc: '2.0',
  id: createRequestId(),
  method,
  params: {
    message: buildMessagePayload({ message, upload_files }, session),
    configuration,
  },
});

export const buildSendMessageRequest = (payload, session) =>
  buildRequest(payload, session, 'message/send', { blocking: true });

const buildStreamMessageRequest = (payload, session) =>
  buildRequest(payload, session, 'message/stream', { blocking: true });

const buildAuthHeaders = (token) => (
  token ? { Authorization: `Bearer ${token}` } : {}
);

export const fetchAgentCard = async (token) => {
  const response = await fetch(`${A2A_BASE_URL}/.well-known/agent-card.json`, {
    headers: buildAuthHeaders(token),
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
      ...buildAuthHeaders(token),
    },
    body: JSON.stringify(buildSendMessageRequest(payload, session)),
  });

  if (!response.ok) {
    throw new Error(`A2A request failed with ${response.status}`);
  }

  return response.json();
};

const waitForNextPaint = () => new Promise((resolve) => {
  if (typeof window !== 'undefined' && typeof window.requestAnimationFrame === 'function') {
    window.requestAnimationFrame(() => resolve());
    return;
  }
  setTimeout(resolve, 0);
});

const processSSEBuffer = async (buffer, onEvent) => {
  const chunks = buffer.split(/\r?\n\r?\n/);
  const remaining = chunks.pop() || '';

  for (const chunk of chunks) {
    const data = chunk
      .split(/\r?\n/)
      .filter((line) => line.startsWith('data:'))
      .map((line) => line.slice(5).trimStart())
      .join('\n');

    if (!data) {
      continue;
    }
    await onEvent(JSON.parse(data));
    await waitForNextPaint();
  }

  return remaining;
};

export const sendA2AMessageStream = async (payload, session, token, onEvent) => {
  const response = await fetch(`${A2A_BASE_URL}/`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      Accept: 'text/event-stream',
      ...buildAuthHeaders(token),
    },
    body: JSON.stringify(buildStreamMessageRequest(payload, session)),
  });

  if (!response.ok) {
    throw new Error(`A2A streaming request failed with ${response.status}`);
  }

  if (!response.body) {
    throw new Error('A2A streaming response body is not available');
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = '';

  while (true) {
    const { done, value } = await reader.read();
    buffer += decoder.decode(value || new Uint8Array(), { stream: !done });
    buffer = await processSSEBuffer(buffer, onEvent);

    if (done) {
      buffer = await processSSEBuffer(buffer, onEvent);
      break;
    }
  }
};

const getField = (obj, ...keys) => {
  for (const key of keys) {
    if (obj && obj[key] !== undefined && obj[key] !== null) {
      return obj[key];
    }
  }
  return null;
};

const extractTextFromParts = (parts = [], { trim = true } = {}) => {
  const text = parts
    .filter((part) => part.kind === 'text' && part.text)
    .map((part) => part.text)
    .join('\n');

  return trim ? text.trim() : text;
};

const extractFilesFromParts = (parts = []) =>
  parts
    .filter((part) => part.kind === 'file' && part.file)
    .map((part) => ({
      name: part.file.name,
      mime_type: part.file.mimeType || part.file.mime_type,
      bytes: part.file.bytes,
    }));

const extractArtifactParts = (task) =>
  (task?.artifacts || []).flatMap((artifact) => artifact?.parts || []);

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
      contextId: getField(result, 'contextId', 'context_id'),
      taskId: getField(result, 'taskId', 'task_id'),
    };
  }

  if (result.kind === 'task') {
    const artifactParts = extractArtifactParts(result);
    const fallbackParts = result.status?.message?.parts || [];

    return {
      content:
        extractTextFromParts(artifactParts) ||
        extractTextFromParts(fallbackParts) ||
        'The task completed without a text response.',
      files: extractFilesFromParts(artifactParts),
      contextId: getField(result, 'contextId', 'context_id'),
      taskId: getField(result, 'id', 'taskId', 'task_id'),
    };
  }

  return {
    content: 'Received an unsupported A2A response shape.',
    files: [],
    contextId: null,
    taskId: null,
  };
};

export const normalizeA2AStreamEvent = (response) => {
  if (response.error) {
    throw new Error(response.error.message || 'A2A streaming request failed');
  }

  const result = response.result;
  if (!result) {
    return { eventType: 'unknown' };
  }

  if (result.kind === 'status-update') {
    return {
      eventType: 'status',
      content: extractTextFromParts(result.status?.message?.parts || []),
      final: Boolean(result.final),
      state: result.status?.state || null,
      contextId: getField(result, 'contextId', 'context_id'),
      taskId: getField(result, 'taskId', 'task_id'),
    };
  }

  if (result.kind === 'artifact-update') {
    const parts = result.artifact?.parts || [];
    return {
      eventType: 'artifact',
      content: extractTextFromParts(parts, { trim: false }),
      files: extractFilesFromParts(parts),
      append: Boolean(result.append),
      lastChunk: Boolean(getField(result, 'lastChunk', 'last_chunk')),
      artifactId: getField(result.artifact, 'artifactId', 'artifact_id'),
      contextId: getField(result, 'contextId', 'context_id'),
      taskId: getField(result, 'taskId', 'task_id'),
    };
  }

  if (result.kind === 'task') {
    return {
      eventType: 'task',
      contextId: getField(result, 'contextId', 'context_id'),
      taskId: getField(result, 'id', 'taskId', 'task_id'),
    };
  }

  if (result.kind === 'message') {
    const normalized = normalizeA2AResponse(response);
    return {
      eventType: 'final',
      ...normalized,
    };
  }

  return {
    eventType: 'unknown',
    contextId: getField(result, 'contextId', 'context_id'),
    taskId: getField(result, 'taskId', 'task_id'),
  };
};
