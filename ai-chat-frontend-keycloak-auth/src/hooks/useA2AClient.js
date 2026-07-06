import { useCallback, useEffect, useRef, useState } from 'react';
import { fetchAgentCard, normalizeA2AResponse, sendA2AMessage } from '../services/a2aClient';

const useA2AClient = (token) => {
  const [isConnected, setIsConnected] = useState(false);
  const [messages, setMessages] = useState([]);
  const [connectionError, setConnectionError] = useState(null);
  const [agentCard, setAgentCard] = useState(null);
  const [isSending, setIsSending] = useState(false);
  const sessionRef = useRef({ contextId: null, taskId: null });

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

    try {
      const rawResponse = await sendA2AMessage(data, sessionRef.current, token);
      const normalized = normalizeA2AResponse(rawResponse);

      sessionRef.current = {
        contextId: normalized.contextId,
        taskId: normalized.taskId,
      };

      setMessages((previous) => [
        ...previous,
        {
          id: Date.now() + Math.random(),
          role: 'assistant',
          content: normalized.content,
          files: normalized.files,
          timestamp: new Date(),
        },
      ]);
    } catch (error) {
      console.error('A2A request failed', error);
      setConnectionError('The A2A request failed. Check the backend server and payload contract.');
    } finally {
      setIsSending(false);
    }
  }, [token]);

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
