# AI Chat Frontend

A React-based chat interface that authenticates with Keycloak and calls a sibling Python A2A backend instead of using a raw WebSocket connection.

## Features

- Keycloak-authenticated chat access
- A2A agent-card discovery
- JSON-RPC chat requests to a paired Python backend
- Role-based message styling (user vs assistant)
- File upload and returned file download support
- Responsive design
- Connection status indicator
- Message timestamps

## Getting Started

### Prerequisites

- Node.js (version 14 or higher)
- npm or yarn

### Installation

1. Install dependencies:
```bash
npm install
```

2. Start the development server:
```bash
npm start
```

The application will open in your browser at `http://localhost:3000`.

### A2A backend configuration

The frontend expects the paired backend in `../ai-chat-backend-a2a` to be running at:

```
http://localhost:8082
```

During development, the React dev server proxies requests to port 8082.

If you need a different backend URL, set:

```bash
REACT_APP_A2A_SERVER_URL=http://your-host:your-port
```

## Usage

1. The app authenticates with Keycloak
2. It loads the A2A agent card from the backend
3. Type your message in the input field at the bottom
4. Press Enter or click the send button to send your message
5. Messages from the assistant are returned as A2A task results
6. Returned file parts can be downloaded from the chat UI
7. Connection status is displayed in the header

## Components

- `App.js` - Main application component
- `ChatWindow.js` - Message display area
- `Message.js` - Individual message component
- `MessageInput.js` - Message input form
- `useA2AClient.js` - Custom hook for A2A agent-card discovery and request flow
- `a2aClient.js` - JSON-RPC request builder and response normalizer

## Styling

The interface uses a clean, modern design with:
- Blue color scheme for user messages
- Gray color scheme for assistant messages
- Visual connection status indicators
- Responsive layout for different screen sizes

## Copilot customization assets

This repository now includes project-specific Copilot assets:

| Concept | Where it lives here | Why it exists |
| --- | --- | --- |
| Custom instructions | `.github/copilot-instructions.md` | Always-on rules for Keycloak + A2A frontend work |
| Custom agents | `.github/agents/frontend-a2a-implementer.agent.md` | A focused implementation persona for auth-aware A2A client changes |
| Agent skills | `.github/skills/frontend-a2a-change/SKILL.md` | A reusable checklist for agent-card discovery, JSON-RPC payloads, and task parsing |
| Subagents | Runtime behavior only | Useful when Copilot needs to investigate frontend, backend, and validation work in parallel |

## Building for Production

```bash
npm run build
```

This creates a `build` folder with the production-ready application.