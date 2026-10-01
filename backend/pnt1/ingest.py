"""Ingestion gateway: envelope validation, size limits, dedupe, dead-letter queue, in-process bus.

Crash-safe by construction (F-98): `ingest()` never raises. Every failure becomes a DLQ entry or a counter.
Payload *content* is not validated here; incomplete or implausible payloads are the Trust Engine's job.
"""
from __future__ import annotations

import json
import time
from collections import OrderedDict, deque
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

MAX_MESSAGE_BYTES = 16 * 1024
EVENT_TYPES = ("telemetry.vehicle", "telemetry.warehouse", "telemetry.shipment", "telemetry.port",
               "signal.alert", "signal.weather")


class Envelope(BaseModel):
    model_config = ConfigDict(extra="forbid")
    event_id: str = Field(min_length=8, max_length=64)
    event_type: Literal["telemetry.vehicle", "telemetry.warehouse", "telemetry.shipment", "telemetry.port",
                        "signal.alert", "signal.weather"]
    source_id: str = Field(min_length=1, max_length=64)
    source_type: Literal["vehicle", "warehouse", "shipment", "port", "alert", "weather"]
    ts_event: datetime
    seq: int = Field(ge=0)
    payload: dict[str, Any]
    run_id: str | None = None
    signature: str | None = None


class Bus:
    """In-process FIFO standing in for Redis Streams at Level 2 (same publish/consume shape)."""

    def __init__(self, maxlen: int = 200_000):
        self._q: deque[Envelope] = deque(maxlen=maxlen)

    def publish(self, env: Envelope) -> None:
        self._q.append(env)

    def drain(self, limit: int = 100_000) -> list[Envelope]:
        out = []
        while self._q and len(out) < limit:
            out.append(self._q.popleft())
        return out

    def __len__(self) -> int:
        return len(self._q)


class Gateway:
    def __init__(self, bus: Bus):
        self.bus = bus
        self._seen: OrderedDict[str, None] = OrderedDict()
        self.dlq: deque[dict] = deque(maxlen=2000)
        self.counts = {"received": 0, "accepted": 0, "dlq": 0, "duplicate": 0}
        self._accepted_times: deque[float] = deque(maxlen=200_000)

    def ingest(self, raw: Any) -> str:
        """Accept one message (dict, str or bytes). Returns 'accepted' | 'duplicate' | 'dlq'. Never raises."""
        self.counts["received"] += 1
        try:
            if isinstance(raw, (bytes, bytearray)):
                if len(raw) > MAX_MESSAGE_BYTES:
                    return self._dead(raw, "oversize")
                raw = raw.decode("utf-8")
            if isinstance(raw, str):
                if len(raw) > MAX_MESSAGE_BYTES:
                    return self._dead(raw, "oversize")
                raw = json.loads(raw)
            if not isinstance(raw, dict):
                return self._dead(raw, "not_an_object")
            env = Envelope.model_validate(raw)
        except (UnicodeDecodeError, json.JSONDecodeError, RecursionError):
            return self._dead(raw, "json_decode")
        except ValidationError as e:
            return self._dead(raw, "envelope_schema", str(e.errors()[:2]))
        except Exception as e:  # noqa: BLE001 - crash safety is the requirement
            return self._dead(raw, "unexpected", repr(e)[:200])
        if env.event_id in self._seen:
            self.counts["duplicate"] += 1
            return "duplicate"
        self._seen[env.event_id] = None
        if len(self._seen) > 500_000:
            self._seen.popitem(last=False)
        self.counts["accepted"] += 1
        self._accepted_times.append(time.monotonic())
        self.bus.publish(env)
        return "accepted"

    def _dead(self, raw: Any, error_class: str, detail: str = "") -> str:
        self.counts["dlq"] += 1
        try:
            preview = raw if isinstance(raw, str) else json.dumps(raw, default=str)
        except Exception:  # noqa: BLE001
            preview = repr(raw)
        self.dlq.append({"error_class": error_class, "detail": detail[:300], "preview": str(preview)[:300],
                         "received_at": time.time()})
        return "dlq"

    def events_per_min(self) -> float:
        now = time.monotonic()
        while self._accepted_times and now - self._accepted_times[0] > 60.0:
            self._accepted_times.popleft()
        if not self._accepted_times:
            return 0.0
        span = max(1.0, min(60.0, now - self._accepted_times[0]))
        return len(self._accepted_times) * 60.0 / span
