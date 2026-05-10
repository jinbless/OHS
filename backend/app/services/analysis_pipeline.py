from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Optional

from sqlalchemy.orm import Session

from app.db import crud
from app.models.analysis import AnalysisResponse
from app.models.hazard import (
    CorrectiveAction,
    Finding,
    PenaltyPath,
    ProcedureStep,
    ReasoningTrace,
    RiskFeature,
    RiskLevel,
    SituationMatch,
    StandardProcedure,
    VisualCue,
    VisualObservation,
)
from app.services import (
    guide_recommendation_service,
    penalty_path_service,
    risk_rule_service,
    situation_assessment_service,
    sr_lookup_service,
)
from app.services.hazard_normalizer import normalize_risk_feature_candidates
from app.services.industry_context import infer_industry_context
from app.utils.taxonomy import get_feature_label


@dataclass
class AnalysisRunInput:
    result: dict
    analysis_type: str
    input_preview: str
    full_description: Optional[str] = None
    declared_industry_text: Optional[str] = None


@dataclass
class AnalysisKnowledgeContext:
    canonical: dict
    risk_features: list[RiskFeature]
    industry_contexts: list[str]
    observable_violation_signal: bool
    she_matches: list[Any]
    actionable_matches: list[Any]
    sr_ids: list[str]
    direct_sr_ids: list[str]
    checklist_rows: list[dict]
    guide_rows: list[dict]
    penalty_paths: list[PenaltyPath]
    finding_status: str
    penalty_exposure_status: str


class AnalysisPipeline:
    """Build the product response from normalized LLM observations.

    AnalysisService owns transport concerns. This pipeline owns business flow:
    observation -> risk features -> SHE/SR -> guide/actions -> penalties.
    """

    async def run(self, db: Session, run_input: AnalysisRunInput) -> AnalysisResponse:
        analysis_id = str(uuid.uuid4())
        analyzed_at = datetime.now()

        observations = self._build_observations(run_input.result)
        context_text = self._context_text(
            run_input.result,
            run_input.full_description,
            run_input.input_preview,
        )
        visual_cues = [cue.text for obs in observations for cue in obs.visual_cues]

        knowledge = self._build_knowledge_context(
            db=db,
            result=run_input.result,
            observations=observations,
            context_text=context_text,
            visual_cues=visual_cues or [context_text],
            declared_industry_text=run_input.declared_industry_text,
        )

        situation_matches = self._build_situation_matches(knowledge.she_matches)
        article_ids = sr_lookup_service.article_ids_for_srs(db, knowledge.sr_ids)
        findings = self._build_findings(
            status=knowledge.finding_status,
            observations=observations,
            situation_matches=situation_matches,
            sr_ids=knowledge.sr_ids,
        )
        reasoning_trace = self._build_reasoning_trace(
            observations=observations,
            risk_features=knowledge.risk_features,
            situation_matches=situation_matches,
            sr_ids=knowledge.sr_ids,
            article_ids=article_ids,
            guide_rows=knowledge.guide_rows,
            checklist_rows=knowledge.checklist_rows,
            penalty_paths=knowledge.penalty_paths,
        )

        summary = run_input.result.get("overall_assessment") or self._summary(
            observations=observations,
            findings=findings,
            penalty_paths=knowledge.penalty_paths,
        )
        overall_risk_level = self._overall_risk_level(
            observations,
            knowledge.finding_status,
        )

        response = AnalysisResponse(
            analysis_id=analysis_id,
            analysis_type=run_input.analysis_type,
            overall_risk_level=RiskLevel(overall_risk_level),
            summary=summary,
            observations=observations,
            risk_features=knowledge.risk_features,
            situation_matches=situation_matches,
            findings=findings,
            immediate_actions=self._build_immediate_actions(
                knowledge.checklist_rows,
                run_input.result.get("immediate_actions", []),
            ),
            standard_procedures=self._build_standard_procedures(knowledge.guide_rows),
            penalty_paths=knowledge.penalty_paths,
            reasoning_trace=reasoning_trace,
            finding_status=knowledge.finding_status,
            penalty_exposure_status=knowledge.penalty_exposure_status,
            analyzed_at=analyzed_at,
        )

        self._persist_response(
            db=db,
            response=response,
            input_preview=run_input.input_preview,
            summary=summary,
            overall_risk_level=overall_risk_level,
        )
        return response

    def _build_knowledge_context(
        self,
        db: Session,
        result: dict,
        observations: list[VisualObservation],
        context_text: str,
        visual_cues: list[str],
        declared_industry_text: Optional[str],
    ) -> AnalysisKnowledgeContext:
        normalized = normalize_risk_feature_candidates(
            result.get("risk_feature_candidates", []),
            context_text=context_text,
        )
        canonical = risk_rule_service.apply_risk_rules(
            normalized,
            db,
            allow_context_only_inference=False,
        )
        risk_features = self._build_risk_features(canonical, normalized)
        industry_context = infer_industry_context(
            work_contexts=canonical["work_contexts"],
            text=context_text,
            declared=declared_industry_text,
        )
        high_severity_observation = any(
            obs.severity == "HIGH" and obs.confidence >= 0.7 for obs in observations
        )
        observable_violation_signal = (
            situation_assessment_service.has_observable_violation_signal(
                normalized=normalized,
                high_severity_observation=high_severity_observation,
                context_text=context_text,
            )
        )

        she_matches = situation_assessment_service.match_situational_patterns(
            db=db,
            canonical=canonical,
            visual_cues=visual_cues,
            industry_contexts=industry_context.active_industries,
        )
        actionable_matches = [
            match for match in she_matches
            if observable_violation_signal
            and match.match_status in situation_assessment_service.ACTIONABLE_MATCH_STATUSES
        ]

        she_sr_ids = [
            sr_id
            for match in actionable_matches
            for sr_id in match.applies_sr_ids
        ]
        direct_sr_ids = [
            sr_id
            for match in she_matches
            if situation_assessment_service.is_direct_penalty_match(match)
            for sr_id in match.applies_sr_ids
        ]

        sr_results = []
        if actionable_matches or observable_violation_signal:
            sr_results = sr_lookup_service.query_safety_requirements(
                db,
                canonical["accident_types"],
                canonical["hazardous_agents"],
                canonical["work_contexts"],
                industry_contexts=industry_context.active_industries,
            )
        sr_ids = self._unique([*she_sr_ids, *[sr["identifier"] for sr in sr_results]])
        direct_sr_ids = self._unique(direct_sr_ids)

        recommendation_matches = actionable_matches
        recommendation_risk_features = risk_features if observable_violation_signal else []

        checklist_rows = guide_recommendation_service.get_immediate_checklist_items(
            db,
            sr_ids,
            direct_sr_ids=direct_sr_ids,
            limit=12,
            risk_features=recommendation_risk_features,
            she_matches=recommendation_matches,
            visual_cues=visual_cues,
            industry_contexts=industry_context.active_industries,
            context_text=" ".join(filter(None, [declared_industry_text, context_text])),
        )
        guide_rows = guide_recommendation_service.get_standard_guides(
            db,
            sr_ids,
            direct_sr_ids=direct_sr_ids,
            limit=6,
            industry_contexts=industry_context.active_industries,
            risk_features=recommendation_risk_features,
            she_matches=recommendation_matches,
            visual_cues=visual_cues,
            context_text=" ".join(filter(None, [declared_industry_text, context_text])),
        )
        penalty_candidates = penalty_path_service.get_penalty_candidates(
            sr_ids,
            direct_sr_ids=direct_sr_ids,
        )
        finding_status = self._finding_status(
            actionable_matches=actionable_matches,
            she_matches=she_matches,
            sr_ids=sr_ids,
            risk_features=risk_features,
            observable_violation_signal=observable_violation_signal,
        )
        penalty_paths = penalty_path_service.build_penalty_paths(
            penalty_candidates,
            finding_status=finding_status,
        )

        return AnalysisKnowledgeContext(
            canonical=canonical,
            risk_features=risk_features,
            industry_contexts=industry_context.active_industries,
            observable_violation_signal=observable_violation_signal,
            she_matches=she_matches,
            actionable_matches=actionable_matches,
            sr_ids=sr_ids,
            direct_sr_ids=direct_sr_ids,
            checklist_rows=checklist_rows,
            guide_rows=guide_rows,
            penalty_paths=penalty_paths,
            finding_status=finding_status,
            penalty_exposure_status=self._penalty_exposure_status(penalty_paths),
        )

    def _build_observations(self, result: dict) -> list[VisualObservation]:
        cues = [
            VisualCue(
                text=item.get("text", ""),
                cue_type=item.get("cue_type", "visual"),
                confidence=float(item.get("confidence", 0) or 0),
            )
            for item in result.get("visual_cues", [])
            if item.get("text")
        ]
        observations = []
        for index, item in enumerate(result.get("visual_observations", []), start=1):
            observations.append(
                VisualObservation(
                    observation_id=f"OBS-{index:03d}",
                    text=item.get("text", ""),
                    confidence=float(item.get("confidence", 0) or 0),
                    severity=item.get("severity", "MEDIUM"),
                    visual_cues=cues,
                )
            )
        if not observations and cues:
            observations.append(
                VisualObservation(
                    observation_id="OBS-001",
                    text="; ".join(cue.text for cue in cues[:3]),
                    confidence=max(cue.confidence for cue in cues),
                    severity="MEDIUM",
                    visual_cues=cues,
                )
            )
        return observations

    def _context_text(
        self,
        result: dict,
        full_description: Optional[str],
        input_preview: str,
    ) -> str:
        parts = [full_description or input_preview]
        parts.extend(item.get("text", "") for item in result.get("visual_observations", []))
        parts.extend(item.get("text", "") for item in result.get("visual_cues", []))
        parts.extend(item.get("text", "") for item in result.get("risk_feature_candidates", []))
        return " ".join(part for part in parts if part)

    def _build_risk_features(self, canonical: dict, normalized: dict) -> list[RiskFeature]:
        axis_fields = [
            ("accident_type", "accident_types"),
            ("hazardous_agent", "hazardous_agents"),
            ("work_context", "work_contexts"),
        ]
        features = []
        for axis, field in axis_fields:
            for code in canonical.get(field, []):
                features.append(
                    RiskFeature(
                        axis=axis,
                        code=code,
                        label=get_feature_label(code),
                        source_text="; ".join(normalized.get("alias_resolved", [])[:3]) or None,
                        confidence=float(canonical.get("confidence", 0) or 0),
                    )
                )
        return features

    def _build_situation_matches(self, she_matches) -> list[SituationMatch]:
        return [
            SituationMatch(
                pattern_id=match.she_id,
                title=getattr(match, "name", None),
                status=getattr(match, "match_status", "candidate"),
                score=float(getattr(match, "match_score", 0) or 0),
                matched_features=list(getattr(match, "matched_dims", []) or []),
                visual_trigger_hits=list(getattr(match, "status_reasons", []) or []),
                applies_sr_ids=list(getattr(match, "applies_sr_ids", []) or []),
                applies_ci_ids=list(getattr(match, "applies_ci_ids", []) or []),
            )
            for match in she_matches
        ]

    def _build_immediate_actions(
        self,
        checklist_rows: list[dict],
        llm_actions: list[str],
    ) -> list[CorrectiveAction]:
        actions = []
        seen = set()
        for row in checklist_rows:
            text = row.get("text")
            if not text or text in seen:
                continue
            seen.add(text)
            actions.append(
                CorrectiveAction(
                    action_id=row.get("identifier") or f"CI-{len(actions) + 1:03d}",
                    title=text,
                    description=row.get("evidence_summary") or row.get("source_section"),
                    source_type="guide:ChecklistItem",
                    source_id=row.get("identifier"),
                    urgency="immediate" if row.get("binding_force") == "MANDATORY" else "planned",
                    confidence=float(row.get("relevance_score", 0.9) or 0.9),
                )
            )
        for text in llm_actions:
            if not text or text in seen:
                continue
            seen.add(text)
            actions.append(
                CorrectiveAction(
                    action_id=f"LLM-ACTION-{len(actions) + 1:03d}",
                    title=text,
                    source_type="app:VisualObservation",
                    urgency="immediate",
                    confidence=0.5,
                )
            )
        return actions[:10]

    def _build_standard_procedures(self, guide_rows: list[dict]) -> list[StandardProcedure]:
        procedures = []
        for row in guide_rows:
            code = row.get("guide_code")
            title = row.get("title")
            if not code or not title:
                continue
            procedures.append(
                StandardProcedure(
                    procedure_id=code,
                    title=f"{code}: {title}",
                    description=(
                        "관련 KOSHA Guide와 작업 프로세스를 기준으로 표준 개선 절차를 검토합니다."
                        if not row.get("evidence_summary")
                        else row.get("evidence_summary")
                    ),
                    guide_code=code,
                    steps=[
                        ProcedureStep(
                            step_id=step.get("step_id") or f"{code}-STEP-{idx + 1}",
                            order=int(step.get("order") or idx + 1),
                            title=step.get("title") or "작업 절차 검토",
                            safety_measures=step.get("safety_measures"),
                            source_section=step.get("source_section"),
                            source_sr_ids=list(step.get("source_sr_ids") or []),
                        )
                        for idx, step in enumerate(row.get("work_process_steps") or [])
                    ],
                    source_sr_ids=list(row.get("source_sr_ids") or []),
                    source_ci_ids=list(row.get("source_ci_ids") or []),
                    evidence_summary=row.get("evidence_summary"),
                    confidence=float(row.get("relevance_score", 0) or 0),
                )
            )
        return procedures

    def _build_findings(
        self,
        status: str,
        observations: list[VisualObservation],
        situation_matches: list[SituationMatch],
        sr_ids: list[str],
    ) -> list[Finding]:
        if not observations and not situation_matches and not sr_ids:
            return []
        return [
            Finding(
                finding_id="FINDING-001",
                status=status,
                summary=self._finding_summary(status, observations, sr_ids),
                evidence_strength=self._evidence_strength(status),
                observation_ids=[obs.observation_id for obs in observations],
                situation_pattern_ids=[match.pattern_id for match in situation_matches],
                sr_ids=sr_ids,
            )
        ]

    def _build_reasoning_trace(
        self,
        observations: list[VisualObservation],
        risk_features: list[RiskFeature],
        situation_matches: list[SituationMatch],
        sr_ids: list[str],
        article_ids: list[str],
        guide_rows: list[dict],
        checklist_rows: list[dict],
        penalty_paths: list[PenaltyPath],
    ) -> ReasoningTrace:
        return ReasoningTrace(
            observations=[obs.observation_id for obs in observations],
            risk_features=[feature.code for feature in risk_features],
            situation_patterns=[match.pattern_id for match in situation_matches],
            safety_requirements=sr_ids,
            articles=article_ids,
            guides=[row.get("guide_code") for row in guide_rows if row.get("guide_code")],
            checklist_items=[row.get("identifier") for row in checklist_rows if row.get("identifier")],
            penalty_rules=self._unique(
                rule_id
                for path in penalty_paths
                for rule_id in path.penalty_rule_ids
            ),
        )

    def _persist_response(
        self,
        db: Session,
        response: AnalysisResponse,
        input_preview: str,
        summary: str,
        overall_risk_level: str,
    ) -> None:
        crud.create_product_analysis_record(
            db=db,
            analysis_id=response.analysis_id,
            analysis_type=response.analysis_type,
            overall_risk_level=overall_risk_level,
            summary=summary,
            input_preview=input_preview,
            result_json=json.loads(response.model_dump_json()),
            observations=[
                obs.model_dump(mode="json") for obs in response.observations
            ],
            risk_features=[
                feature.model_dump(mode="json") for feature in response.risk_features
            ],
        )

    def _finding_status(
        self,
        actionable_matches,
        she_matches,
        sr_ids: list[str],
        risk_features: list[RiskFeature],
        observable_violation_signal: bool,
    ) -> str:
        confirmed_matches = [
            match for match in actionable_matches
            if getattr(match, "match_status", "") == "confirmed"
        ]
        candidate_matches = [
            match for match in actionable_matches
            if getattr(match, "match_status", "") == "candidate"
        ]
        if confirmed_matches and sr_ids:
            return "confirmed"
        if candidate_matches and sr_ids:
            if any(self._match_needs_confirmation(match) for match in candidate_matches):
                return "needs_clarification"
            return "suspected"
        if sr_ids:
            return "suspected" if observable_violation_signal else "needs_clarification"
        if she_matches:
            return "needs_clarification" if observable_violation_signal else "not_determined"
        if risk_features:
            return "needs_clarification" if observable_violation_signal else "not_determined"
        return "not_determined"

    def _match_needs_confirmation(self, match) -> bool:
        reasons = set(getattr(match, "status_reasons", []) or [])
        return (
            getattr(match, "match_status", "") == "review_candidate"
            or "confirmation_required" in reasons
            or any(reason.startswith("indirect_") for reason in reasons)
        )

    def _evidence_strength(self, status: str) -> str:
        if status == "confirmed":
            return "high"
        if status == "suspected":
            return "medium"
        return "low"

    def _penalty_exposure_status(self, penalty_paths: list[PenaltyPath]) -> str:
        if any(path.notice_level == "photo_based" for path in penalty_paths):
            return "direct"
        if penalty_paths:
            return "conditional"
        return "no_penalty"

    def _overall_risk_level(
        self,
        observations: list[VisualObservation],
        finding_status: str,
    ) -> str:
        if finding_status == "confirmed" and any(obs.severity == "HIGH" for obs in observations):
            return "high"
        if finding_status in {"confirmed", "suspected"}:
            return "medium"
        return "low"

    def _summary(
        self,
        observations: list[VisualObservation],
        findings: list[Finding],
        penalty_paths: list[PenaltyPath],
    ) -> str:
        if findings:
            penalty_text = " 벌칙 안내 경로가 있습니다." if penalty_paths else ""
            return f"{findings[0].summary}{penalty_text}"
        if observations:
            return observations[0].text
        return "사진 또는 설명에서 확정 가능한 위험 단서를 찾지 못했습니다."

    def _finding_summary(
        self,
        status: str,
        observations: list[VisualObservation],
        sr_ids: list[str],
    ) -> str:
        status_label = {
            "confirmed": "확인된 위험",
            "suspected": "의심 위험",
            "needs_clarification": "추가 확인 필요",
            "not_determined": "판단 불가",
        }.get(status, status)
        base = observations[0].text if observations else "관찰 사실 없음"
        if sr_ids:
            return f"{status_label}: {base} 관련 안전요구사항 {len(sr_ids)}건이 연결되었습니다."
        return f"{status_label}: {base}"

    def _unique(self, values) -> list:
        return list(dict.fromkeys(value for value in values if value))


analysis_pipeline = AnalysisPipeline()
