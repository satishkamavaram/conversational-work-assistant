import React, { useState, useEffect } from 'react';
import './Message.css';

// Renders a single file attachment delivered through A2A: decodes the base64
// bytes into a Blob URL so we can both preview (PDF) and download it.
const FileAttachment = ({ file }) => {
  const fileName = file?.name || 'document';
  const fileMime = file?.mime_type || file?.mimeType || 'application/octet-stream';

  const [fileUrl, setFileUrl] = useState(null);

  // Create the Blob URL inside the effect (not useMemo). React 18 StrictMode
  // runs effects setup -> cleanup -> setup in dev; creating the URL here means
  // the second setup recreates it after the first cleanup revokes it, so the
  // URL stays valid (otherwise the download link points at a revoked blob and
  // the browser reports a network/"check internet connection" error).
  useEffect(() => {
    if (!file?.bytes) {
      setFileUrl(null);
      return;
    }
    let url = null;
    try {
      const byteChars = atob(file.bytes);
      const byteArray = new Uint8Array(byteChars.length);
      for (let i = 0; i < byteChars.length; i++) {
        byteArray[i] = byteChars.charCodeAt(i);
      }
      url = URL.createObjectURL(new Blob([byteArray], { type: fileMime }));
      setFileUrl(url);
    } catch (e) {
      console.error('Failed to decode file bytes', e);
      setFileUrl(null);
    }
    return () => {
      if (url) URL.revokeObjectURL(url);
    };
  }, [file, fileMime]);

  if (!fileUrl) return null;

  return (
    <div className="message-file">
      <div className="message-file-header">
        <span className="message-file-name">📄 {fileName}</span>
        <a className="message-file-download" href={fileUrl} download={fileName}>
          ⬇ Download
        </a>
      </div>
      {fileMime === 'application/pdf' && (
        <iframe className="message-file-preview" title={fileName} src={fileUrl} />
      )}
    </div>
  );
};

const Message = ({ message, role }) => {
  const formatTime = (timestamp) => {
    return new Date(timestamp).toLocaleTimeString('en-US', {
      hour: '2-digit',
      minute: '2-digit'
    });
  };

  // one or more files (e.g. CV PDF) delivered through A2A
  const files = message.files || [];

  // Heuristic: detect ASCII/Markdown tables, including ones without leading/trailing pipes.
  const isAsciiTable = (text) => {
    if (typeof text !== 'string') return false;
    const lines = text.split('\n');
    // Lines that contain column separators
    const pipeLines = lines.filter(l => l.includes('|'));
    // Border/separator rows like "-----+------" or "|-----|"
    const hasBorder = lines.some(l => /^[-+|\s]+$/.test(l.trim()));
    // Consider it a table if we see at least two lines with pipes (header+row)
    // or a classic border row
    return pipeLines.length >= 2 || hasBorder;
  };

  return (
    <div className={`message ${role}`}>
      <div className="message-content">
        <div className="message-header">
          <span className="message-role">{role === 'user' ? 'You' : 'Assistant'}</span>
          <span className="message-time">{formatTime(message.timestamp)}</span>
        </div>
        {isAsciiTable(message.content) ? (
          <pre className="message-text pre">{message.content}</pre>
        ) : (
          <div className="message-text">{message.content}</div>
        )}
        {files.map((file, idx) => (
          <FileAttachment key={`${file.name || 'file'}-${idx}`} file={file} />
        ))}
      </div>
    </div>
  );
};

export default Message;
