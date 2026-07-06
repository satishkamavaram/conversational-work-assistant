import React, { useState, useRef } from 'react';
import { Send, Paperclip, X } from 'lucide-react';
import './MessageInput.css';

const MAX_FILE_SIZE_MB = 10;

const readFileAsBase64 = (file) =>
  new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => {
      // result is "data:<mime>;base64,<b64>" — strip the prefix
      const b64 = reader.result.split(',')[1];
      resolve(b64);
    };
    reader.onerror = reject;
    reader.readAsDataURL(file);
  });

const MessageInput = ({ onSendMessage, disabled }) => {
  const [message, setMessage] = useState('');
  const [selectedFiles, setSelectedFiles] = useState([]);
  const fileInputRef = useRef(null);

  const handleFileChange = (e) => {
    const incoming = Array.from(e.target.files || []);
    const valid = incoming.filter((f) => {
      if (f.size > MAX_FILE_SIZE_MB * 1024 * 1024) {
        alert(`"${f.name}" is larger than ${MAX_FILE_SIZE_MB} MB and was skipped.`);
        return false;
      }
      return true;
    });
    setSelectedFiles((prev) => {
      const existing = new Set(prev.map((f) => f.name));
      return [...prev, ...valid.filter((f) => !existing.has(f.name))];
    });
    // reset so the same file can be re-selected after removal
    e.target.value = '';
  };

  const removeFile = (name) =>
    setSelectedFiles((prev) => prev.filter((f) => f.name !== name));

  const handleSubmit = async (e) => {
    e.preventDefault();
    if (disabled) return;
    if (!message.trim() && selectedFiles.length === 0) return;

    let uploadFileParts = [];
    if (selectedFiles.length > 0) {
      uploadFileParts = await Promise.all(
        selectedFiles.map(async (file) => ({
          name: file.name,
          mime_type: file.type || 'application/octet-stream',
          bytes: await readFileAsBase64(file),
        }))
      );
    }

    const payload = { message: message.trim() };
    if (uploadFileParts.length > 0) {
      payload.upload_files = uploadFileParts;
    }

    // send through existing WebSocket — file bytes travel as A2A FileParts,
    // never entering the LLM context (mirroring the download pattern)
    onSendMessage(payload);

    setMessage('');
    setSelectedFiles([]);
  };

  const handleKeyPress = (e) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleSubmit(e);
    }
  };

  const canSend = (message.trim() || selectedFiles.length > 0) && !disabled;

  return (
    <form onSubmit={handleSubmit} className="message-input-form">
      {selectedFiles.length > 0 && (
        <div className="file-chips">
          {selectedFiles.map((f) => (
            <span key={f.name} className="file-chip">
              📄 {f.name}
              <button
                type="button"
                className="file-chip-remove"
                onClick={() => removeFile(f.name)}
                aria-label={`Remove ${f.name}`}
              >
                <X size={12} />
              </button>
            </span>
          ))}
        </div>
      )}
      <div className="input-container">
        <input
          ref={fileInputRef}
          type="file"
          multiple
          onChange={handleFileChange}
          style={{ display: 'none' }}
        />
        <button
          type="button"
          className="attach-button"
          onClick={() => fileInputRef.current?.click()}
          disabled={disabled}
          title="Attach files"
        >
          <Paperclip size={20} />
        </button>
        <textarea
          value={message}
          onChange={(e) => setMessage(e.target.value)}
          onKeyPress={handleKeyPress}
          placeholder="Type your message..."
          disabled={disabled}
          className="message-textarea"
          rows="1"
        />
        <button
          type="submit"
          disabled={!canSend}
          className="send-button"
        >
          <Send size={20} />
        </button>
      </div>
    </form>
  );
};

export default MessageInput;