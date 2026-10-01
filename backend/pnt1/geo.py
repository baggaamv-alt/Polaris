"""Small geodesy helpers (km, degrees). Local equirectangular projection is accurate enough at link scale."""
from __future__ import annotations

import math

import numpy as np

EARTH_R_KM = 6371.0
KM_PER_DEG_LAT = 110.57


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lon2 - lon1)
    h = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * EARTH_R_KM * math.asin(min(1.0, math.sqrt(h)))


def bearing_deg(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dl = math.radians(lon2 - lon1)
    x = math.sin(dl) * math.cos(p2)
    y = math.cos(p1) * math.sin(p2) - math.sin(p1) * math.cos(p2) * math.cos(dl)
    return (math.degrees(math.atan2(x, y)) + 360.0) % 360.0


def segment_distances_km(lat: float, lon: float, segs: np.ndarray) -> np.ndarray:
    """Distance (km) from a point to each segment. segs: (N, 4) array of lat1, lon1, lat2, lon2."""
    if len(segs) == 0:
        return np.empty(0)
    kx = 111.32 * math.cos(math.radians(lat))
    ax = (segs[:, 1] - lon) * kx
    ay = (segs[:, 0] - lat) * KM_PER_DEG_LAT
    bx = (segs[:, 3] - lon) * kx
    by = (segs[:, 2] - lat) * KM_PER_DEG_LAT
    dx, dy = bx - ax, by - ay
    len2 = dx * dx + dy * dy
    t = np.where(len2 > 0, -(ax * dx + ay * dy) / np.where(len2 > 0, len2, 1.0), 0.0)
    t = np.clip(t, 0.0, 1.0)
    px, py = ax + t * dx, ay + t * dy
    return np.sqrt(px * px + py * py)


def offset_point(lat: float, lon: float, bearing: float, dist_km: float) -> tuple[float, float]:
    """Move a point dist_km along a bearing (flat-earth approximation, fine for < 50 km)."""
    b = math.radians(bearing)
    dlat = dist_km * math.cos(b) / KM_PER_DEG_LAT
    dlon = dist_km * math.sin(b) / (111.32 * math.cos(math.radians(lat)))
    return lat + dlat, lon + dlon
