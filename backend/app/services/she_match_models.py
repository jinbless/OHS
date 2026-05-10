from __future__ import annotations


class SHEMatchResult:
    """Matched reusable SHE pattern with scoring metadata."""

    def __init__(
        self,
        she_id: str,
        name: str,
        features: dict,
        broadness: float,
        match_score: float,
        matched_dims: list[str],
        visual_score: float,
        match_status: str,
        status_reasons: list[str],
        industry_hints: list[str],
        industry_alignment: str,
        industry_reasons: list[str],
        source_sr_ids: list[str],
        applies_sr_ids: list[str],
        applies_ci_ids: list[str],
        source_guides: list[str],
    ):
        self.she_id = she_id
        self.name = name
        self.features = features
        self.broadness = broadness
        self.match_score = match_score
        self.matched_dims = matched_dims
        self.visual_score = visual_score
        self.match_status = match_status
        self.status_reasons = status_reasons
        self.industry_hints = industry_hints
        self.industry_alignment = industry_alignment
        self.industry_reasons = industry_reasons
        self.source_sr_ids = source_sr_ids
        self.applies_sr_ids = applies_sr_ids
        self.applies_ci_ids = applies_ci_ids
        self.source_guides = source_guides

    def to_dict(self) -> dict:
        return {
            "she_id": self.she_id,
            "name": self.name,
            "features": self.features,
            "broadness": self.broadness,
            "match_score": self.match_score,
            "matched_dims": self.matched_dims,
            "visual_score": self.visual_score,
            "match_status": self.match_status,
            "status_reasons": self.status_reasons,
            "industry_hints": self.industry_hints,
            "industry_alignment": self.industry_alignment,
            "industry_reasons": self.industry_reasons,
            "applies_sr_ids": self.applies_sr_ids,
            "applies_ci_count": len(self.applies_ci_ids),
            "source_guides": self.source_guides,
        }
