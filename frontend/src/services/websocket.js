import { useCallback, useEffect, useRef, useState } from "react";

const WS_URL = "ws://localhost:8000/ws";
const RECONNECT_DELAY_MS = 2000;

export function useAgentSocket(url = WS_URL) {
  const [status, setStatus] = useState("connecting");
  const [actions, setActions] = useState([]);
  const [lastRaw, setLastRaw] = useState(null);
  const wsRef = useRef(null);
  const reconnectTimer = useRef(null);

  useEffect(() => {
    let cancelled = false;

    const connect = () => {
      setStatus("connecting");
      const ws = new WebSocket(url);
      wsRef.current = ws;

      ws.onopen = () => {
        if (cancelled) return;
        setStatus("open");
      };

      ws.onmessage = (event) => {
        if (cancelled) return;
        setLastRaw(event.data);

        try {
          const parsed = JSON.parse(event.data);
          if (parsed && parsed.action && parsed.policy) {
            setActions((prev) => [parsed, ...prev]);
          }
        } catch {
          // Not JSON yet (e.g. plain "Hello" ping payload from the current
          // backend stub) — that's fine, lastRaw already captured it above.
        }
      };

      ws.onclose = () => {
        if (cancelled) return;
        setStatus("closed");
        reconnectTimer.current = setTimeout(connect, RECONNECT_DELAY_MS);
      };

      ws.onerror = () => {
        if (cancelled) return;
        setStatus("error");
      };
    };

    connect();

    return () => {
      cancelled = true;
      clearTimeout(reconnectTimer.current);
      wsRef.current?.close();
    };
  }, [url]);

  const sendPing = useCallback(() => {
    if (wsRef.current?.readyState === WebSocket.OPEN) {
      wsRef.current.send("ping");
    }
  }, []);

  const addMockAction = useCallback((record) => {
    setActions((prev) => [record, ...prev]);
  }, []);

  return { status, actions, lastRaw, sendPing, addMockAction };
}