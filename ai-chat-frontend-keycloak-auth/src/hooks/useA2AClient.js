import { useCallback, useEffect, useRef, useState } from 'react';
import { flushSync } from 'react-dom';
import {
  fetchAgentCard,
  normalizeA2AResponse,
  normalizeA2AStreamEvent,
  sendA2AMessage,
  sendA2AMessageStream,
} from '../services/a2aClient';

const useA2AClient = (token) => {
  const [isConnected, setIsConnected] = useState(false);
  const [messages, setMessages] = useState([]);
  const [connectionError, setConnectionError] = useState(null);
  const [agentCard, setAgentCard] = useState(null);
  const [isSending, setIsSending] = useState(false);
  const sessionRef = useRef({ contextId: null, taskId: null });

  const appendFiles = useCallback((existingFiles = [], incomingFiles = []) => {
    if (incomingFiles.length === 0) return existingFiles;

    const merged = [...existingFiles];
    incomingFiles.forEach((file) => {
      const alreadyExists = merged.some(
        (existing) => existing.name === file.name && existing.bytes === file.bytes
      );
      if (!alreadyExists) {
        merged.push(file);
      }
    });
    return merged;
  }, []);

  const appendEvent = useCallback((existingEvents = [], eventText) => {
    if (!eventText) return existingEvents;
    if (existingEvents[existingEvents.length - 1] === eventText) return existingEvents;
    return [...existingEvents, eventText];
  }, []);

  const connect = useCallback(async () => {
    if (!token) {
      setIsConnected(false);
      setAgentCard(null);
      setConnectionError(null);
      return;
    }

    try {
      const card = await fetchAgentCard(token);
      setAgentCard(card);
      setIsConnected(true);
      setConnectionError(null);
    } catch (error) {
      console.error('Failed to load A2A agent card', error);
      setAgentCard(null);
      setIsConnected(false);
      setConnectionError('Unable to connect to the A2A backend');
    }
  }, [token]);

  const disconnect = useCallback(() => {
    sessionRef.current = { contextId: null, taskId: null };
    setAgentCard(null);
    setIsConnected(false);
    setConnectionError(null);
  }, []);

  const isTerminalTaskError = useCallback(
    (error) => Boolean(error?.message && error.message.includes('terminal state')),
    []
  );

  const sendMessage = useCallback(async (payload) => {
    if (!token) {
      setConnectionError('You must be authenticated before calling the A2A backend');
      return;
    }

    setIsSending(true);
    setConnectionError(null);

    const data = typeof payload === 'string' ? { message: payload } : payload;
    const fileNames = (data.upload_files || []).map((file) => file.name);
    const displayContent = [data.message, ...fileNames.map((name) => `📎 ${name}`)]
      .filter(Boolean)
      .join('\n');

    setMessages((previous) => [
      ...previous,
      {
        id: Date.now() + Math.random(),
        role: 'user',
        content: displayContent,
        timestamp: new Date(),
      },
    ]);

    const assistantMessageId = Date.now() + Math.random();
    setMessages((previous) => [
      ...previous,
      {
        id: assistantMessageId,
        role: 'assistant',
        content: '',
        files: [],
        events: [],
        responseReady: false,
        isStreaming: true,
        statusText: 'Connecting to A2A stream…',
        timestamp: new Date(),
      },
    ]);

    const applyStreamEvent = (event) => {
      flushSync(() => {
        setMessages((previous) =>
          previous.map((message) => {
            if (message.id !== assistantMessageId) return message;

            if (event.eventType === 'status') {
              const activityText = event.content || null;
              return {
                ...message,
                statusText: activityText || message.statusText,
                events: appendEvent(message.events, activityText),
                isStreaming: !event.final,
              };
            }

            if (event.eventType === 'artifact') {
              const nextContent = event.content
                ? (event.append ? `${message.content}${event.content}` : event.content)
                : message.content;
              const responseReady = Boolean(
                message.responseReady ||
                event.lastChunk ||
                (!event.append && message.content)
              );
              return {
                ...message,
                content: nextContent,
                files: appendFiles(message.files, event.files || []),
                responseReady,
                isStreaming: !event.lastChunk,
                statusText: message.statusText,
              };
            }

            if (event.eventType === 'final') {
              return {
                ...message,
                content: event.content,
                files: event.files,
                responseReady: true,
                isStreaming: false,
                statusText: message.statusText,
              };
            }

            return message;
          })
        );
      });
    };

    const runStreamRequest = async (allowRetry = true) => {
      try {
        await sendA2AMessageStream(
          data,
          sessionRef.current,
          token,
          async (rawEvent) => {
            const event = normalizeA2AStreamEvent(rawEvent);

            sessionRef.current = {
              contextId: event.contextId || sessionRef.current.contextId,
              taskId: event.final ? null : (event.taskId || sessionRef.current.taskId),
            };

            applyStreamEvent(event);
          }
        );
      } catch (error) {
        if (allowRetry && isTerminalTaskError(error) && sessionRef.current.taskId) {
          sessionRef.current = {
            contextId: sessionRef.current.contextId,
            taskId: null,
          };
          return runStreamRequest(false);
        }
        throw error;
      }
    };

    try {
      if (agentCard?.capabilities?.streaming) {
        await runStreamRequest();
      } else {
        const rawResponse = await sendA2AMessage(data, sessionRef.current, token);
        const normalized = normalizeA2AResponse(rawResponse);

        sessionRef.current = {
          contextId: normalized.contextId,
          taskId: null,
        };

        setMessages((previous) =>
          previous.map((message) =>
            message.id === assistantMessageId
              ? {
                  ...message,
                  content: normalized.content,
                  files: normalized.files,
                  responseReady: true,
                  isStreaming: false,
                  statusText: null,
                }
              : message
          )
        );
      }
    } catch (error) {
      console.error('A2A request failed', error);
      setConnectionError('The A2A request failed. Check the backend server and payload contract.');
      setMessages((previous) =>
        previous.map((message) =>
          message.id === assistantMessageId
            ? {
                ...message,
                isStreaming: false,
                statusText: 'Streaming request failed',
              }
            : message
        )
      );
    } finally {
      setMessages((previous) =>
        previous.map((message) =>
          message.id === assistantMessageId
            ? { ...message, isStreaming: false }
            : message
        )
      );
      setIsSending(false);
    }
  }, [agentCard, appendEvent, appendFiles, isTerminalTaskError, token]);

  useEffect(() => {
    connect();
  }, [connect]);

  return {
    agentCard,
    connect,
    connectionError,
    disconnect,
    isConnected,
    isSending,
    messages,
    sendMessage,
  };
};

export default useA2AClient;
