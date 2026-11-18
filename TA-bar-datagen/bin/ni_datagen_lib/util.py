"""Small shared helpers: deterministic randomness, timestamps, IDs."""
from __future__ import annotations

import hashlib
import math
import random
import uuid
from datetime import datetime, timezone

# Copied from network_intelligence/bin/model/identity.py so backfilled health
# observations reference the same vertex IDs the app's materializer computes.
VERTEX_NAMESPACE = uuid.UUID("aacbd024-d0f2-514a-9f02-640a5825faea")


def stable_rng(*parts) -> random.Random:
    """A Random seeded from the given parts, identical across runs and processes."""
    digest = hashlib.sha256("|".join(str(p) for p in parts).encode()).digest()
    return random.Random(int.from_bytes(digest[:8], "big"))


def stable_hex(*parts, length: int = 32) -> str:
    return hashlib.sha256("|".join(str(p) for p in parts).encode()).hexdigest()[:length]


def rng_uuid(rng: random.Random) -> str:
    return str(uuid.UUID(int=rng.getrandbits(128), version=4))


def vertex_id_for(canonical_key: str) -> str:
    return str(uuid.uuid5(VERTEX_NAMESPACE, canonical_key))


def iso_z(ts: float, micro: bool = False) -> str:
    dt = datetime.fromtimestamp(ts, tz=timezone.utc)
    if micro:
        return dt.strftime("%Y-%m-%dT%H:%M:%S.%fZ")
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def jitter(rng: random.Random, value: float, pct: float) -> float:
    return value * (1.0 + rng.uniform(-pct, pct))


def diurnal(ts: float, utc_offset_h: int) -> float:
    """Business-hours load factor in [0.15, 1.0], lower on weekends."""
    local = datetime.fromtimestamp(ts + utc_offset_h * 3600, tz=timezone.utc)
    hour = local.hour + local.minute / 60.0
    if 7 <= hour <= 19:
        factor = 0.35 + 0.65 * math.sin(math.pi * (hour - 7) / 12.0)
    else:
        factor = 0.15
    if local.weekday() >= 5:
        factor *= 0.4
    return max(0.15, factor)
