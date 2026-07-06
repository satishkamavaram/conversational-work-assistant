import React, { useEffect, useState } from 'react';
import { Wifi, WifiOff, MessageCircle } from 'lucide-react';
import useA2AClient from './hooks/useA2AClient';
import ChatWindow from './components/ChatWindow';
import MessageInput from './components/MessageInput';
import './App.css';
import keycloak from './auth/keycloak';

function App() {
  const [kcReady, setKcReady] = useState(false);
  const [kcAuthenticated, setKcAuthenticated] = useState(false);
  const [token, setToken] = useState(null);

  // Initialize Keycloak on app load
  useEffect(() => {
    let mounted = true;
    // Attach listeners early to ensure token is captured whenever auth completes
    keycloak.onAuthSuccess = () => {
      setKcAuthenticated(true);
      setToken(keycloak.token || null);
    };
    keycloak.onAuthRefreshSuccess = () => {
      setToken(keycloak.token || null);
    };
    keycloak.onTokenExpired = async () => {
      try {
        const refreshed = await keycloak.updateToken(0);
        if (refreshed) {
          setToken(keycloak.token || null);
        } else {
          // If not refreshed, force re-login
          setKcAuthenticated(false);
          setToken(null);
          await keycloak.login();
        }
      } catch {
        setKcAuthenticated(false);
        setToken(null);
        try { await keycloak.login(); } catch { /* ignore */ }
      }
    };
    keycloak.onAuthRefreshError = async () => {
      // If refresh fails, redirect to login
      setKcAuthenticated(false);
      setToken(null);
      try { await keycloak.login(); } catch { /* ignore */ }
    };

    keycloak.init({
      onLoad: 'login-required',
      checkLoginIframe: false,
      pkceMethod: 'S256',
      // If you later choose 'check-sso', uncomment the next line and add public/silent-check-sso.html
      // silentCheckSsoRedirectUri: window.location.origin + '/silent-check-sso.html',
    }).then((authenticated) => {
      if (!mounted) return;
      setKcReady(true);
      setKcAuthenticated(!!authenticated);
      if (authenticated) {
        setToken(keycloak.token || null);
      }
    }).catch(() => {
      // If Keycloak is unavailable, keep waiting (no anonymous fallback)
      setKcReady(true);
      setKcAuthenticated(false);
    });
    return () => { mounted = false; };
  }, []);

  // Refresh token periodically when logged in
  useEffect(() => {
    if (!kcAuthenticated) return;
    const interval = setInterval(async () => {
      try {
        const refreshed = await keycloak.updateToken(30);
        if (refreshed) setToken(keycloak.token || null);
      } catch (_) {
        // ignore
      }
    }, 20000);
    return () => clearInterval(interval);
  }, [kcAuthenticated]);

  const { agentCard, isConnected, isSending, messages, sendMessage, connectionError, disconnect } = useA2AClient(token);

  const handleLogout = async () => {
    try { disconnect && disconnect(); } catch { /* no-op */ }
    try {
      setToken(null);
      setKcAuthenticated(false);
      await keycloak.logout({ redirectUri: window.location.origin });
    } catch (e) {
      console.error('Logout failed', e);
    }
  };

  // Gate UI: When using 'login-required', Keycloak redirects to login if needed.
  if (!kcReady || !kcAuthenticated) {
    return <div className="App" style={{ padding: 24 }}>Loading…</div>;
  }


  return (
    <div className="App">
      <header className="app-header">
        <div className="header-left">
          <MessageCircle size={24} />
          <div>
            <h1>AI Agent</h1>
            <p className="header-subtitle">
              {agentCard ? `${agentCard.name} via A2A` : 'A2A client'}
            </p>
          </div>
        </div>
        <div className="connection-status" style={{ display: 'flex', gap: 12, alignItems: 'center' }}>
          {isConnected ? (
            <div className="status connected">
              <Wifi size={16} />
              <span>Connected</span>
            </div>
          ) : (
            <div className="status disconnected">
              <WifiOff size={16} />
              <span>Disconnected</span>
            </div>
          )}
          <button onClick={handleLogout} style={{
            padding: '6px 10px',
            borderRadius: 6,
            border: '1px solid #ccc',
            background: '#fff',
            cursor: 'pointer'
          }}>Logout</button>
        </div>
      </header>

      {connectionError && (
        <div className="error-banner">
          <p>Connection Error: {connectionError}</p>
        </div>
      )}

      <main className="app-main">
        <ChatWindow messages={messages} />
        <MessageInput
          onSendMessage={sendMessage}
          disabled={!isConnected || isSending}
        />
      </main>
    </div>
  );
}

export default App;