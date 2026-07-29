"""
tracer.py — Lightweight tracing shim, shaped like AWS X-Ray segments.

Why this exists (Milestone 3 — AWS Integration + Demo Lock):
  We want the pipeline (planner call -> step execution -> browser action)
  to be instrumented with real timing NOW, without requiring AWS credentials
  or the aws-xray-sdk during the hackathon. Segments/subsegments are written
  as local JSON files in the exact shape AWS X-Ray uses (trace_id, id, name,
  start_time, end_time, subsegments[]), so switching to the real AWS X-Ray
  daemon later is a one-line change (TRACE_BACKEND=xray), not a rewrite.

Usage:
    from app.tracing.tracer import tracer

    with tracer.segment("chat_task", trace_id=session_id) as seg:
        with seg.subsegment("planner.generate_plan"):
            plan = generate_plan(user_task)

        with seg.subsegment("llm.get_next_action"):
            action = browser_agent.think(dom)

        with seg.subsegment("browser.execute_action"):
            _execute(page, action)

Backends:
    TRACE_BACKEND=local (default) -> writes JSON trace files to
        backend/logs/traces/<trace_id>.json
    TRACE_BACKEND=xray -> lazy-imports aws_xray_sdk; only touched if you
        actually set this env var, so `local` mode never needs the
        dependency installed. This is the hook to wire real AWS X-Ray on
        the last day — see _emit_xray() below for exactly where.
"""

import os
import json
import time
import uuid
import threading
from pathlib import Path
from contextlib import contextmanager

TRACE_BACKEND = os.getenv("TRACE_BACKEND", "local")  # "local" | "xray"

_LOG_DIR = Path(__file__).resolve().parents[2] / "logs" / "traces"
_lock = threading.Lock()


def _now_ms() -> float:
    return time.time() * 1000


class _Subsegment:
    def __init__(self, name: str, parent_id: str):
        self.id = uuid.uuid4().hex[:16]
        self.parent_id = parent_id
        self.name = name
        self.start_time = _now_ms()
        self.end_time = None
        self.metadata = {}
        self.error = None

    def set_metadata(self, **kwargs):
        self.metadata.update(kwargs)

    def to_dict(self):
        return {
            "id": self.id,
            "parent_id": self.parent_id,
            "name": self.name,
            "start_time": self.start_time,
            "end_time": self.end_time,
            "duration_ms": (
                round(self.end_time - self.start_time, 2) if self.end_time else None
            ),
            "metadata": self.metadata,
            "error": self.error,
        }


class _Segment:
    """
    A root segment (one per task run / chat session). Holds a list of
    subsegments in the order they finished, mirroring AWS X-Ray's shape.
    """

    def __init__(self, name: str, trace_id: str | None = None):
        self.trace_id = trace_id or uuid.uuid4().hex
        self.id = uuid.uuid4().hex[:16]
        self.name = name
        self.start_time = _now_ms()
        self.end_time = None
        self.subsegments: list[dict] = []
        self.metadata = {}

    def set_metadata(self, **kwargs):
        self.metadata.update(kwargs)

    @contextmanager
    def subsegment(self, name: str, **metadata):
        sub = _Subsegment(name, parent_id=self.id)
        if metadata:
            sub.set_metadata(**metadata)
        try:
            yield sub
        except Exception as exc:
            sub.error = str(exc)
            raise
        finally:
            sub.end_time = _now_ms()
            self.subsegments.append(sub.to_dict())

    def start_subsegment(self, name: str, **metadata) -> "_Subsegment":
        """Non-context-manager variant — call finish_subsegment() when done."""
        sub = _Subsegment(name, parent_id=self.id)
        if metadata:
            sub.set_metadata(**metadata)
        return sub

    def finish_subsegment(self, sub: "_Subsegment", error: str | None = None):
        sub.end_time = _now_ms()
        if error:
            sub.error = error
        self.subsegments.append(sub.to_dict())

    def to_dict(self):
        return {
            "trace_id": self.trace_id,
            "id": self.id,
            "name": self.name,
            "start_time": self.start_time,
            "end_time": self.end_time,
            "duration_ms": (
                round(self.end_time - self.start_time, 2) if self.end_time else None
            ),
            "metadata": self.metadata,
            "subsegments": self.subsegments,
        }


class Tracer:
    """
    Entry point. `tracer.segment(...)` is a context manager that yields a
    _Segment you can open subsegments on. On exit, the segment is flushed
    to whichever backend is configured.
    """

    @contextmanager
    def segment(self, name: str, trace_id: str | None = None, **metadata):
        seg = _Segment(name, trace_id=trace_id)
        if metadata:
            seg.set_metadata(**metadata)
        try:
            yield seg
        finally:
            seg.end_time = _now_ms()
            self._flush(seg)

    def start_segment(self, name: str, trace_id: str | None = None, **metadata) -> _Segment:
        """Non-context-manager variant — call finish_segment() when done."""
        seg = _Segment(name, trace_id=trace_id)
        if metadata:
            seg.set_metadata(**metadata)
        return seg

    def finish_segment(self, seg: _Segment):
        seg.end_time = _now_ms()
        self._flush(seg)

    def _flush(self, seg: _Segment):
        if TRACE_BACKEND == "xray":
            self._emit_xray(seg)
        else:
            self._emit_local(seg)

    def _emit_local(self, seg: _Segment):
        with _lock:
            _LOG_DIR.mkdir(parents=True, exist_ok=True)
            out_path = _LOG_DIR / f"{seg.trace_id}.json"
            try:
                existing = json.loads(out_path.read_text()) if out_path.exists() else []
            except Exception:
                existing = []
            existing.append(seg.to_dict())
            out_path.write_text(json.dumps(existing, indent=2))

    def _emit_xray(self, seg: _Segment):
        """
        Real AWS X-Ray hook — wire this on the last day.
        Expects `aws-xray-sdk` installed and AWS credentials/region set.
        Left unimplemented on purpose: swap in aws_xray_sdk.core.xray_recorder
        calls here, matching the same segment/subsegment structure above,
        without changing any call sites in agent.py / playwright_agent.py.
        """
        try:
            from aws_xray_sdk.core import xray_recorder  # noqa: F401
        except ImportError:
            print(
                "[tracer] TRACE_BACKEND=xray but aws-xray-sdk is not installed — "
                "falling back to local trace file. Run `pip install aws-xray-sdk` "
                "and implement _emit_xray() to enable real AWS X-Ray."
            )
            self._emit_local(seg)
            return

        # TODO (last day): translate seg.to_dict() into xray_recorder calls.
        self._emit_local(seg)  # always keep a local copy too, for now


tracer = Tracer()
