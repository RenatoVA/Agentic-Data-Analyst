from __future__ import annotations

import hashlib


def sha256_from_named_bytes(parts: dict[str, bytes]) -> str:
    hasher = hashlib.sha256()
    for name in sorted(parts.keys()):
        hasher.update(name.encode("utf-8"))
        hasher.update(b"\x00")
        hasher.update(parts[name])
        hasher.update(b"\x00")
    return hasher.hexdigest()

