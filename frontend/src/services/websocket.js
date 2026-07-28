import { useCallback, useEffect, useRef, useState } from "react";

const WS_URL = "ws://localhost:8000/ws";
const RECONNECT_DELAY_MS = 2000;

export function useAgentSocket(url = WS_URL) {
  const [status,    setStatus]    = useState("connecting");
  const [actions,   setActions]   = useState([]);   // { action, policy } events only
  const [rawEvents, setRawEvents] = useState([]);   // every parsed WS message (newest first)
  const wsRef           = useRef(null);
  const reconnectTimer  = useRef(null);

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

        try {
          const parsed = JSON.parse(event.data);

          // Always push to rawEvents so ChatPanel can read chat_status events
          setRawEvents((prev) => [parsed, ...prev]);

          // Only push to actions if this looks like an agent action payload
          // Handles both tagged payloads ({ type:"action", action, policy })
          // and the legacy untagged format ({ action, policy }) from /run-agent.
          const isAction =
            (parsed.type === "action" || (!parsed.type && parsed.action && parsed.policy));

          if (isAction && parsed.action && parsed.policy) {
            setActions((prev) => [parsed, ...prev]);
          }
        } catch {
          // Non-JSON ping/pong — ignore
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
    setRawEvents((prev) => [record, ...prev]);
  }, []);

  return { status, actions, rawEvents, sendPing, addMockAction };
}
