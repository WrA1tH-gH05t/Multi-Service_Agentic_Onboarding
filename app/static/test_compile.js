
        const { useState, useRef, useEffect, useCallback } = React;

        const API_BASE = 'http://localhost:8000/api/v1';

        function App() {
            const [sidebarOpen, setSidebarOpen] = useState(true);
            const [messages, setMessages] = useState([]);
            const [input, setInput] = useState('');
            const [file, setFile] = useState(null);
            const [loading, setLoading] = useState(false);
            const [showAuth, setShowAuth] = useState(false);
            const [user, setUser] = useState(null);
            const [authMode, setAuthMode] = useState('login');
            const [authData, setAuthData] = useState({ username: '', password: '', name: '' });
            const [authError, setAuthError] = useState('');
            const [services, setServices] = useState([]);
            const [documents, setDocuments] = useState([]);
            const [showDocumentsPage, setShowDocumentsPage] = useState(false);
            const [showServicesPage, setShowServicesPage] = useState(false);
            const [systemHealthy, setSystemHealthy] = useState(false);
            const [ollamaHealthy, setOllamaHealthy] = useState(false);
            const chatEndRef = useRef(null);
            const fileInputRef = useRef(null);

            // Refs to avoid stale closures
            const messagesRef = useRef([]);
            const loadingRef = useRef(false);

            useEffect(() => {
                messagesRef.current = messages;
            }, [messages]);

            useEffect(() => {
                loadingRef.current = loading;
            }, [loading]);

            useEffect(() => {
                loadServices();
                loadDocuments();
                checkAuth();
                checkHealth();
                // Poll health every 30s
                const interval = setInterval(checkHealth, 30000);
                return () => clearInterval(interval);
            }, []);

            useEffect(() => {
                chatEndRef.current?.scrollIntoView({ behavior: 'smooth' });
            }, [messages]);

            const checkAuth = async () => {
                const token = localStorage.getItem('token');
                const username = localStorage.getItem('username');
                if (token && username) {
                    setUser({ token, username });
                }
            };

            const checkHealth = async () => {
                try {
                    const res = await fetch(`${API_BASE}/health`);
                    const data = await res.json();
                    setSystemHealthy(data.status === 'healthy');
                    setOllamaHealthy(data.services?.generation === 'healthy' || data.services?.generation === 'model_not_found');
                } catch (e) {
                    setSystemHealthy(false);
                    setOllamaHealthy(false);
                }
            };

            const loadServices = async () => {
                try {
                    const res = await fetch(`${API_BASE}/services`);
                    const data = await res.json();
                    setServices(data.data?.services || []);
                } catch (e) {
                    console.error('Failed to load services:', e);
                }
            };

            const loadDocuments = async () => {
                try {
                    const res = await fetch(`${API_BASE}/documents`);
                    const data = await res.json();
                    setDocuments(data.data?.documents || []);
                } catch (e) {
                    console.error('Failed to load documents:', e);
                }
            };

            const handleAuth = async () => {
                setAuthError('');
                try {
                    const endpoint = authMode === 'login' ? '/auth/login' : '/auth/register';
                    const body = authMode === 'login'
                        ? { username: authData.username, password: authData.password }
                        : { username: authData.username, password: authData.password, name: authData.name || authData.username };

                    const res = await fetch(`${API_BASE}${endpoint}`, {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify(body)
                    });

                    const data = await res.json();

                    if (authMode === 'login' && data.success) {
                        localStorage.setItem('token', data.data.token);
                        localStorage.setItem('username', data.data.email || authData.username);
                        setUser({ token: data.data.token, username: data.data.email || authData.username });
                        setShowAuth(false);
                    } else if (authMode === 'register' && data.success) {
                        setAuthMode('login');
                        alert('Account created! Please login.');
                    } else {
                        setAuthError(data.detail || data.error || 'Authentication failed');
                    }
                } catch (e) {
                    setAuthError('Connection error');
                }
            };

            const handleLogout = () => {
                localStorage.removeItem('token');
                localStorage.removeItem('username');
                setUser(null);
            };

            const handleFileUpload = async () => {
                if (!file) return;

                const formData = new FormData();
                formData.append('file', file);

                try {
                    const res = await fetch(`${API_BASE}/documents/upload`, {
                        method: 'POST',
                        body: formData
                    });

                    const data = await res.json();
                    if (data.success) {
                        addMessage('system', `✅ Document uploaded: ${file.name}`);
                        setFile(null);
                        if (fileInputRef.current) fileInputRef.current.value = '';
                        loadDocuments();
                    } else {
                        addMessage('system', `❌ Upload failed: ${data.detail || 'Unknown error'}`);
                    }
                } catch (e) {
                    addMessage('system', `❌ Upload error: ${e.message}`);
                }
            };

            const sendMessage = async (messageText) => {
                const query = messageText || input.trim();
                if (!query && !file) return;
                if (loadingRef.current) return;

                const userMessage = query;
                addMessage('user', userMessage);

                setLoading(true);
                setInput('');
                setFile(null);
                if (fileInputRef.current) fileInputRef.current.value = '';

                try {
                    const res = await fetch(`${API_BASE}/chat/message`, {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ query: userMessage })
                    });

                    const data = await res.json();

                    let responseText = data.response || 'No response';
                    let matchedService = data.matched_service;

                    if (data.sources && data.sources.length > 0) {
                        const sourceNames = data.sources.map(s => s.filename).join(', ');
                        responseText += `\n\n📚 Sources: ${sourceNames}`;
                    }

                    if (data.confidence !== undefined) {
                        responseText += `\n\n🎯 Confidence: ${(data.confidence * 100).toFixed(0)}%`;
                    }

                    addMessage('assistant', responseText, matchedService);
                } catch (e) {
                    addMessage('assistant', `Error: ${e.message}`);
                } finally {
                    setLoading(false);
                }
            };

            const addMessage = (role, content, service = null) => {
                setMessages(prev => [...prev, { role, content, service, timestamp: new Date() }]);
            };

            const formatFileSize = (bytes) => {
                if (bytes < 1024) return bytes + ' B';
                if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(1) + ' KB';
                return (bytes / (1024 * 1024)).toFixed(1) + ' MB';
            };

            const getServiceIcon = (serviceId) => {
                const icons = {
                    basic_registration: '🆔',
                    premium_crossborder: '🌍',
                    mobility_rental: '🚗'
                };
                return icons[serviceId] || '📋';
            };

            const handleFeatureClick = (messageText) => {
                if (messageText === 'Upload a document') {
                    fileInputRef.current?.click();
                } else {
                    addMessage('user', messageText);
                    sendMessage(messageText);
                }
            };

            const handleServiceClick = (serviceId, serviceName) => {
                addMessage('user', `Tell me about ${serviceName}`);
                sendMessage(`Tell me about ${serviceName}`);
            };

            const renderDocumentsPage = () => (
                <div className="chat-area">
                    <div style={{ padding: '24px' }}>
                        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '24px' }}>
                            <h2 style={{ fontSize: '20px', fontWeight: '600' }}>
                                <i className="fas fa-folder" style={{ marginRight: '8px' }}></i>
                                Uploaded Documents ({documents.length})
                            </h2>
                            <button className="btn btn-secondary" onClick={() => setShowDocumentsPage(false)}>
                                <i className="fas fa-arrow-left" style={{ marginRight: '4px' }}></i>
                                Back to Chat
                            </button>
                        </div>
                        
                        {documents.length === 0 ? (
                            <div style={{ textAlign: 'center', padding: '60px 20px', color: '#666' }}>
                                <div style={{ fontSize: '48px', marginBottom: '16px' }}>📄</div>
                                <div style={{ fontSize: '18px', marginBottom: '8px' }}>No documents yet</div>
                                <div style={{ fontSize: '14px', color: '#888' }}>
                                    Upload your first document using the paperclip icon in the chat input
                                </div>
                            </div>
                        ) : (
                            <div style={{ display: 'grid', gap: '12px' }}>
                                {documents.map((doc, idx) => (
                                    <div key={idx} style={{
                                        padding: '16px',
                                        background: '#1a1a1a',
                                        border: '1px solid #2a2a2a',
                                        borderRadius: '12px',
                                        display: 'flex',
                                        alignItems: 'center',
                                        gap: '12px'
                                    }}>
                                        <div style={{ fontSize: '24px' }}>📄</div>
                                        <div style={{ flex: 1 }}>
                                            <div style={{ fontSize: '14px', fontWeight: '500', marginBottom: '4px' }}>
                                                {doc.filename || doc.name || 'Unknown file'}
                                            </div>
                                            <div style={{ fontSize: '12px', color: '#666' }}>
                                                {doc.upload_date || doc.date || doc.uploaded_at || 'Unknown date'}
                                                {' · '}{formatFileSize(doc.file_size || doc.size || 0)}
                                            </div>
                                        </div>
                                        <div style={{ fontSize: '12px', color: '#22c55e' }}>
                                            Processed
                                        </div>
                                    </div>
                                ))}
                            </div>
                        )}
                    </div>
                </div>
            );

            const renderServicesPage = () => (
                <div className="chat-area">
                    <div style={{ padding: '24px' }}>
                        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '24px' }}>
                            <h2 style={{ fontSize: '20px', fontWeight: '600' }}>
                                <i className="fas fa-cogs" style={{ marginRight: '8px' }}></i>
                                Services
                            </h2>
                            <button className="btn btn-secondary" onClick={() => setShowServicesPage(false)}>
                                <i className="fas fa-arrow-left" style={{ marginRight: '4px' }}></i>
                                Back to Chat
                            </button>
                        </div>
                        
                        {services.length === 0 ? (
                            <div style={{ textAlign: 'center', padding: '60px 20px', color: '#666' }}>
                                <div style={{ fontSize: '48px', marginBottom: '16px' }}>🔧</div>
                                <div style={{ fontSize: '18px', marginBottom: '8px' }}>No services available</div>
                                <div style={{ fontSize: '14px', color: '#888' }}>
                                    No services have been loaded yet. Please check the system configuration.
                                </div>
                            </div>
                        ) : (
                            <div style={{ display: 'grid', gap: '16px' }}>
                                {services.map((svc, idx) => (
                                    <div key={idx} style={{
                                        padding: '20px',
                                        background: '#1a1a1a',
                                        border: '1px solid #2a2a2a',
                                        borderRadius: '12px',
                                        display: 'flex',
                                        flexDirection: 'column',
                                        gap: '12px'
                                    }}>
                                        <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
                                            <div style={{ fontSize: '28px' }}>{getServiceIcon(svc.id)}</div>
                                            <div style={{ flex: 1 }}>
                                                <div style={{ fontSize: '16px', fontWeight: '600' }}>{svc.name}</div>
                                                <div style={{ fontSize: '12px', color: svc.status === 'available' ? '#22c55e' : '#666', marginTop: '2px' }}>
                                                    {svc.status === 'available' ? '● Available' : '○ Coming Soon'}
                                                </div>
                                            </div>
                                            <button className="btn btn-primary" onClick={() => {
                                                setShowServicesPage(false);
                                                addMessage('user', `Tell me about ${svc.name}`);
                                                sendMessage(`Tell me about ${svc.name}`);
                                            }} style={{ padding: '6px 16px', fontSize: '13px' }}>
                                                Ask about this
                                            </button>
                                        </div>
                                        <div style={{ fontSize: '14px', color: '#ccc', lineHeight: '1.5' }}>
                                            {svc.description || 'No description available.'}
                                        </div>
                                        <div style={{ display: 'flex', flexWrap: 'wrap', gap: '16px', fontSize: '13px', color: '#888' }}>
                                            <div>
                                                <strong style={{ color: '#aaa' }}>Required Documents:</strong>
                                                <div style={{ marginTop: '4px' }}>
                                                    {(svc.documents_required || []).length > 0 
                                                        ? (svc.documents_required || []).map((d, i) => (
                                                            <span key={i} style={{ 
                                                                display: 'inline-block', 
                                                                padding: '2px 8px', 
                                                                background: '#2a2a2a', 
                                                                borderRadius: '4px', 
                                                                marginRight: '4px',
                                                                fontSize: '12px'
                                                            }}>{d.replace(/_/g, ' ')}</span>
                                                        ))
                                                        : <span style={{ color: '#666' }}>None specified</span>
                                                    }
                                                </div>
                                            </div>
                                            <div>
                                                <strong style={{ color: '#aaa' }}>Processing Time:</strong>
                                                <span style={{ marginLeft: '8px' }}>{svc.processing_time || 'TBD'}</span>
                                            </div>
                                        </div>
                                    </div>
                                ))}
                            </div>
                        )}
                    </div>
                </div>
            );

            // Auth Modal
            if (showAuth) {
                return (
                    <div className="modal-overlay">
                        <div className="modal">
                            <div className="modal-title">
                                {authMode === 'login' ? 'Welcome Back' : 'Create Account'}
                            </div>
                            <div className="modal-subtitle">
                                {authMode === 'login' ? 'Sign in to continue' : 'Get started with DocIntake'}
                            </div>

                            <div className="form-group">
                                <label>Username</label>
                                <input
                                    className="form-input"
                                    value={authData.username}
                                    onChange={e => setAuthData({ ...authData, username: e.target.value })}
                                    placeholder="Enter username"
                                />
                            </div>

                            <div className="form-group">
                                <label>Password</label>
                                <input
                                    className="form-input"
                                    type="password"
                                    value={authData.password}
                                    onChange={e => setAuthData({ ...authData, password: e.target.value })}
                                    placeholder="Enter password"
                                    onKeyDown={e => e.key === 'Enter' && handleAuth()}
                                />
                            </div>

                            {authMode === 'register' && (
                                <div className="form-group">
                                    <label>Name (optional)</label>
                                    <input
                                        className="form-input"
                                        value={authData.name}
                                        onChange={e => setAuthData({ ...authData, name: e.target.value })}
                                        placeholder="Enter your name"
                                    />
                                </div>
                            )}

                            {authError && (
                                <div>
                                    <div className="error-msg">{authError}</div>
                                    <div style={{ display: 'flex', gap: '8px', marginTop: '8px' }}>
                                        <button
                                            className="btn btn-ghost"
                                            onClick={() => setAuthError('')}
                                            style={{ flex: 1 }}
                                        >
                                            Try again
                                        </button>
                                        <button
                                            className="btn btn-ghost"
                                            onClick={() => setShowAuth(false)}
                                            style={{ flex: 1 }}
                                        >
                                            Cancel
                                        </button>
                                    </div>
                                </div>
                            )}

                            <button className="btn btn-primary" onClick={handleAuth} style={{ width: '100%', marginTop: '16px' }}>
                                {authMode === 'login' ? 'Sign In' : 'Create Account'}
                            </button>

                            <button
                                className="btn btn-ghost"
                                onClick={() => {
                                    setAuthMode(authMode === 'login' ? 'register' : 'login');
                                    setAuthError('');
                                }}
                                style={{ width: '100%', marginTop: '8px' }}
                            >
                                {authMode === 'login' ? "Don't have an account? Sign up" : 'Already have an account? Sign in'}
                            </button>
                        </div>
                    </div>
                );
            }

            return (
                <div>
                    {/* Top bar */}
                    <div className="topbar">
                        <div className="topbar-left">
                            <button className="sidebar-toggle" onClick={() => setSidebarOpen(!sidebarOpen)}>
                                <i className="fas fa-bars"></i>
                            </button>
                            <div className="logo">DocIntake</div>
                        </div>
                        <div className="topbar-right">
                            {user ? (
                                <>
                                    <span style={{ fontSize: '13px', color: '#888' }}>Logged in as {user.username}</span>
                                    <button className="btn btn-ghost" onClick={handleLogout}>
                                        <i className="fas fa-sign-out-alt"></i> Logout
                                    </button>
                                </>
                            ) : (
                                <button className="btn btn-primary" onClick={() => setShowAuth(true)}>
                                    <i className="fas fa-user"></i> Login
                                </button>
                            )}
                        </div>
                    </div>

                    {/* Main layout */}
                    <div className="main-layout">
                        {/* Sidebar */}
                        <div className={`sidebar ${!sidebarOpen ? 'collapsed' : ''}`}>
                            <div className="sidebar-header">
                                <button className="new-chat-btn" onClick={() => setMessages([])}>
                                    <i className="fas fa-plus"></i>
                                    New Chat
                                </button>
                            </div>

                            <div className="sidebar-section">
                                <div className="sidebar-section-title">Navigation</div>
                                <div className="sidebar-item active" onClick={() => { setShowDocumentsPage(false); setShowServicesPage(false); setMessages([]); }}>
                                    <i className="fas fa-comment"></i> Chat
                                </div>
                                <div className="sidebar-item" onClick={() => { setShowServicesPage(true); setShowDocumentsPage(false); }}>
                                    <i className="fas fa-cogs"></i> Services
                                </div>
                                <div className="sidebar-item" onClick={() => { setShowDocumentsPage(true); setShowServicesPage(false); loadDocuments(); }}>
                                    <i className="fas fa-folder"></i> Documents
                                    <span style={{ marginLeft: 'auto', fontSize: '12px', color: '#666' }}>{documents.length}</span>
                                </div>
                            </div>

                            {services.length > 0 && (
                                <div className="sidebar-section">
                                    <div className="sidebar-section-title">Services</div>
                                    {services.map(svc => (
                                        <div key={svc.id} className="sidebar-item" onClick={() => handleServiceClick(svc.id, svc.name)}>
                                            <span>{getServiceIcon(svc.id)}</span>
                                            {svc.name}
                                        </div>
                                    ))}
                                </div>
                            )}

                            <div className="sidebar-status">
                                <div className="status-item">
                                    <div className={`status-dot ${systemHealthy ? '' : 'offline'}`}></div>
                                    <span style={{ color: systemHealthy ? '#22c55e' : '#666' }}>
                                        {systemHealthy ? 'System Online' : 'System Offline'}
                                    </span>
                                </div>
                                <div className="status-item">
                                    <div className={`status-dot ${ollamaHealthy ? '' : 'offline'}`}></div>
                                    <span style={{ color: ollamaHealthy ? '#22c55e' : '#666' }}>
                                        {ollamaHealthy ? 'Ollama Connected' : 'Ollama Offline'}
                                    </span>
                                </div>
                            </div>
                        </div>

                        {/* Chat area */}
                        {showServicesPage ? (
                            renderServicesPage()
                        ) : showDocumentsPage ? (
                            renderDocumentsPage()
                        ) : (
                            <div className="chat-area">
                            <div className="chat-messages">
                                {messages.length === 0 ? (
                                    <div className="welcome-message">
                                        <div className="welcome-icon">📄</div>
                                        <div className="welcome-title">Welcome to DocIntake</div>
                                        <div className="welcome-text">AI-powered document onboarding assistant</div>
                                        <div className="feature-grid">
                                            <div className="feature-card" onClick={() => handleFeatureClick('I want to apply for basic registration')}>
                                                <div className="feature-icon">🆔</div>
                                                <div className="feature-title">Basic Registration</div>
                                                <div className="feature-desc">Simple identity registration</div>
                                            </div>
                                            <div className="feature-card" onClick={() => handleFeatureClick('I want to apply for premium cross-border service')}>
                                                <div className="feature-icon">🌍</div>
                                                <div className="feature-title">Cross Border</div>
                                                <div className="feature-desc">International verification</div>
                                            </div>
                                            <div className="feature-card" onClick={() => handleFeatureClick('I need mobility or rental service')}>
                                                <div className="feature-icon">🚗</div>
                                                <div className="feature-title">Mobility/Rental</div>
                                                <div className="feature-desc">Vehicle rental service</div>
                                            </div>
                                            <div className="feature-card" onClick={() => handleFeatureClick('Upload a document')}>
                                                <div className="feature-icon">📎</div>
                                                <div className="feature-title">Upload Document</div>
                                                <div className="feature-desc">Attach PDF files</div>
                                            </div>
                                        </div>
                                    </div>
                                ) : (
                                    <>
                                        {messages.map((msg, idx) => (
                                            msg.role === 'system' ? (
                                                <div key={idx} className="system-message">
                                                    <div className="message-content">
                                                        {msg.content}
                                                    </div>
                                                </div>
                                            ) : (
                                                <div key={idx} className={`message ${msg.role}`}>
                                                    <div className="message-avatar">
                                                        {msg.role === 'assistant' ? '🤖' : '👤'}
                                                    </div>
                                                    <div>
                                                        <div className="message-content">
                                                            {msg.content.split('\n').map((line, i) => (
                                                                <div key={i}>{line}</div>
                                                            ))}
                                                        </div>
                                                        {msg.service && (
                                                            <div className="service-badge">
                                                                <span>{getServiceIcon(msg.service)}</span>
                                                                <span>Connected to: {msg.service.replace(/_/g, ' ').replace(/\b\w/g, c => c.toUpperCase())}</span>
                                                            </div>
                                                        )}
                                                    </div>
                                                </div>
                                            )
                                        ))}
                                    </>
                                )}
                                {loading && (
                                    <div className="message assistant">
                                        <div className="message-avatar">🤖</div>
                                        <div className="message-content">
                                            <div className="typing-indicator">
                                                <div className="typing-dot"></div>
                                                <div className="typing-dot"></div>
                                                <div className="typing-dot"></div>
                                            </div>
                                        </div>
                                    </div>
                                )}
                                <div ref={chatEndRef} />
                            </div>

                            <div className="chat-input-area">
                                <div className="input-container">
                                    {file && (
                                        <div className="file-preview">
                                            <i className="fas fa-file-pdf"></i>
                                            <span>{file.name}</span>
                                            <span className="file-remove" onClick={() => { setFile(null); if (fileInputRef.current) fileInputRef.current.value = ''; }}>
                                                <i className="fas fa-times"></i>
                                            </span>
                                            <button className="btn btn-primary" onClick={handleFileUpload} style={{ marginLeft: 'auto', padding: '4px 12px', fontSize: '12px' }}>
                                                Upload
                                            </button>
                                        </div>
                                    )}
                                    <div className="input-wrapper">
                                        <button className="upload-btn" onClick={() => fileInputRef.current?.click()}>
                                            <i className="fas fa-paperclip"></i>
                                        </button>
                                        <input
                                            type="file"
                                            ref={fileInputRef}
                                            accept=".pdf"
                                            style={{ display: 'none' }}
                                            onChange={e => setFile(e.target.files[0])}
                                        />
                                        <textarea
                                            id="chatInput"
                                            value={input}
                                            onChange={e => setInput(e.target.value)}
                                            placeholder="Type your message..."
                                            rows="1"
                                            onKeyDown={e => {
                                                if (e.key === 'Enter' && !e.shiftKey) {
                                                    e.preventDefault();
                                                    sendMessage();
                                                }
                                            }}
                                        />
                                        <button className="send-btn" onClick={() => sendMessage()} disabled={loading}>
                                            <i className="fas fa-paper-plane"></i>
                                        </button>
                                    </div>
                                </div>
                            </div>
                        </div>
                        )}
                    </div>
                </div>
            );
        }

        ReactDOM.createRoot(document.getElementById('root')).render(<App />);
    