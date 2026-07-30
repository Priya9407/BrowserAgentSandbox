import React, { useState } from 'react';

export default function Chat({ messages, onSendMessage }) {
  const [input, setInput] = useState('');

  const handleSend = () => {
    if (!input.trim()) return;
    onSendMessage(input);
    setInput('');
  };

  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: '100%', borderRight: '1px solid #ccc' }}>
      <div style={{ padding: '10px', background: '#111827', color: '#fff', fontWeight: 'bold' }}>
        Agent Chat
      </div>
      <div style={{ flex: 1, overflowY: 'auto', padding: '15px', backgroundColor: '#f9fafb' }}>
        {messages.length === 0 && (
          <div style={{ textAlign: 'center', color: '#6b7280', marginTop: '20px' }}>
            Enter a URL at the top and say hello to start!
          </div>
        )}
        {messages.map((msg, i) => (
          <div key={i} style={{
            marginBottom: '15px',
            textAlign: msg.role === 'user' ? 'right' : 'left'
          }}>
            <div style={{
              display: 'inline-block',
              padding: '10px 15px',
              borderRadius: '18px',
              backgroundColor: msg.role === 'user' ? '#2563eb' : '#fff',
              color: msg.role === 'user' ? '#fff' : '#1f2937',
              boxShadow: msg.role === 'agent' ? '0 1px 3px rgba(0,0,0,0.1)' : 'none',
              border: msg.role === 'agent' ? '1px solid #e5e7eb' : 'none',
              maxWidth: '85%',
              textAlign: 'left'
            }}>
              {msg.content}
            </div>
          </div>
        ))}
      </div>
      <div style={{ padding: '15px', borderTop: '1px solid #e5e7eb', display: 'flex', backgroundColor: '#fff' }}>
        <input 
          style={{ flex: 1, padding: '12px', borderRadius: '8px', border: '1px solid #d1d5db', outline: 'none' }}
          value={input}
          onChange={e => setInput(e.target.value)}
          onKeyDown={e => e.key === 'Enter' && handleSend()}
          placeholder="Ask the agent to do something..."
        />
        <button onClick={handleSend} style={{ 
          marginLeft: '10px', padding: '12px 20px', borderRadius: '8px', 
          backgroundColor: '#2563eb', color: '#fff', border: 'none', cursor: 'pointer', fontWeight: 'bold'
        }}>
          Send
        </button>
      </div>
    </div>
  );
}
