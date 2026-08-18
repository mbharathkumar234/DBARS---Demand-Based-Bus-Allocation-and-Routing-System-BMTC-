from __future__ import annotations

import hashlib
from typing import Dict, List, Optional
from .text import normalize_text


class StopRegistry:
    def __init__(self, mapping: Optional[Dict[str, str]] = None):
        self._norm_to_id: Dict[str, str] = mapping or {}

    @classmethod
    def build(cls, stop_names: List[str], coordinates: Optional[Dict[str, tuple]] = None) -> StopRegistry:
        mapping: Dict[str, str] = {}
        for stop in sorted(stop_names):
            norm = normalize_text(stop)
            if norm and norm not in mapping:
                stop_hash = hashlib.md5(norm.encode("utf-8")).hexdigest()[:8].upper()
                mapping[norm] = f"STOP_{stop_hash}"
        return cls(mapping)

    def id_for(self, stop_name: Optional[str]) -> Optional[str]:
        if not stop_name:
            return None
        norm = normalize_text(stop_name)
        if norm in self._norm_to_id:
            return self._norm_to_id[norm]
        stop_hash = hashlib.md5(norm.encode("utf-8")).hexdigest()[:8].upper()
        return f"STOP_{stop_hash}"
