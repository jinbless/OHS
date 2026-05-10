"""risk:RiskFeature catalog 조회 유틸리티."""

import json
from pathlib import Path
from typing import Optional

_CATALOG = None


def _load_catalog() -> dict:
    global _CATALOG
    if _CATALOG is None:
        path = Path(__file__).parent.parent / "data" / "risk_feature_catalog.json"
        with open(path, "r", encoding="utf-8") as f:
            _CATALOG = json.load(f)
    return _CATALOG


def get_axis_codes(axis: str) -> dict:
    catalog = _load_catalog()
    axis_data = catalog.get("axes", {}).get(axis, {})
    return axis_data.get("codes", {})


def get_axis_label(axis: str) -> str:
    catalog = _load_catalog()
    return catalog.get("axes", {}).get(axis, {}).get("label", axis)


def get_all_axis_code_list(axis: str) -> list[str]:
    codes = get_axis_codes(axis)
    result = []
    for code, info in codes.items():
        result.append(code)
        result.extend(info.get("sub", []))
    return result


def get_feature_label(code: str) -> Optional[str]:
    catalog = _load_catalog()
    for axis_data in catalog.get("axes", {}).values():
        for item_code, info in axis_data.get("codes", {}).items():
            if item_code == code:
                return info.get("label", code)
            if code in info.get("sub", []):
                return info.get("label", code)
    return None


def get_axes() -> list[str]:
    catalog = _load_catalog()
    return list(catalog.get("axes", {}).keys())
