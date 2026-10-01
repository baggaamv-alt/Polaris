"""Network degradation modes (F-14): NORMAL -> DEGRADED -> BLIND -> RECOVERY -> NORMAL."""
from __future__ import annotations

from . import config
from .trust import TrustEngine
from .twin import Twin


class ModeController:
    def __init__(self, twin: Twin, trust: TrustEngine, n_warehouses: int, n_vehicles: int, n_ports: int):
        self.twin, self.trust = twin, trust
        self.mode = "NORMAL"
        self.freshness = 1.0
        self.coverage = 1.0
        self._pending: tuple[str, float] | None = None
        self._recovery_since: float | None = None
        self.expected = {"vehicle": n_vehicles, "warehouse": n_warehouses, "port": n_ports}
        self.history: list[dict] = []

    def measure(self, now: float) -> tuple[float, float]:
        fresh = total = 0
        thr_v = config.GPS_INTERVAL_S * config.FRESH_FACTOR
        vs = list(self.twin.vehicles.values())
        total += self.expected["vehicle"]
        fresh += sum(1 for v in vs if now - v.t <= thr_v)
        thr_w = config.WAREHOUSE_INTERVAL_S * config.FRESH_FACTOR
        total += self.expected["warehouse"]
        fresh += sum(1 for t in self.twin.warehouse_t.values() if now - t <= thr_w)
        thr_p = config.PORT_INTERVAL_S * config.FRESH_FACTOR
        total += self.expected["port"]
        fresh += sum(1 for t in self.twin.port_t.values() if now - t <= thr_p)
        ents = [e for e in self.trust.entities.values() if e.kind in ("vehicle", "warehouse_feed")]
        cov = sum(1 for e in ents if e.cls == "trusted") / len(ents) if ents else 1.0
        return (fresh / total if total else 1.0), cov

    def _target(self, f: float, c: float) -> str:
        if f < config.F_BLIND:
            return "BLIND"
        ok = f >= config.F_NORMAL and c >= config.C_NORMAL
        if self.mode == "NORMAL":
            return "NORMAL" if ok else "DEGRADED"
        if self.mode == "BLIND":
            return "DEGRADED"
        if self.mode == "DEGRADED":
            return "RECOVERY" if ok else "DEGRADED"
        if self.mode == "RECOVERY":
            return "RECOVERY" if ok else "DEGRADED"
        return self.mode

    def tick(self, now: float) -> dict | None:
        """Returns a mode.changed event dict when the mode changes."""
        self.freshness, self.coverage = self.measure(now)
        target = self._target(self.freshness, self.coverage)
        if self.mode == "RECOVERY" and target == "RECOVERY":
            if self._recovery_since is not None and now - self._recovery_since >= config.MODE_STABILITY_S:
                return self._switch("NORMAL", now, "stable after recovery; reconciliation complete")
            return None
        if target == self.mode:
            self._pending = None
            return None
        if self._pending is None or self._pending[0] != target:
            self._pending = (target, now)
            return None
        if now - self._pending[1] >= config.MODE_HYSTERESIS_S:
            return self._switch(target, now, f"F={self.freshness:.0%} C={self.coverage:.0%}")
        return None

    def _switch(self, to: str, now: float, reason: str) -> dict:
        ev = {"t": now, "from": self.mode, "to": to, "freshness": round(self.freshness, 3),
              "coverage": round(self.coverage, 3), "reason": reason}
        self.mode = to
        self._pending = None
        self._recovery_since = now if to == "RECOVERY" else None
        self.history.append(ev)
        return ev
