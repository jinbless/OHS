from typing import Optional
from datetime import datetime
import json
import uuid
from pathlib import Path
from sqlalchemy.orm import Session

import logging

from app.integrations.openai_client import openai_client
from app.services.video_service import video_service
from app.services.article_service import article_service
from app.services.guide_service import guide_service
from app.services.ontology_service import ontology_service
from app.services.search_enhancer import (
    extract_keywords_for_search,
    rewrite_queries_batch,
    rerank_results,
)
from app.models.analysis import AnalysisResponse, NormContext, LinkedGuideSummary, SparqlEnrichmentSummary
from app.models.guide import GuideMatch, GuideArticleRef
from app.models.hazard import (
    Hazard, RiskLevel, HazardCategory, NormSummary,
    FacetedHazardCodes, GptFreeObservation, CodeGapWarning, PenaltyInfo,
)
from app.models.checklist import Checklist, ChecklistItem
from app.db import crud
from app.utils.exceptions import OpenAIAPIError
from app.services.hazard_normalizer import normalize_faceted_hazards
from app.services import hazard_rule_engine
from app.services.divergence_detector import detect_divergence, save_gaps_to_db

logger = logging.getLogger(__name__)

# ── 키워드 매핑 테이블 로드 ───────────────────────────────────
_KEYWORD_MAPPINGS = None

def _load_keyword_mappings() -> dict:
    global _KEYWORD_MAPPINGS
    if _KEYWORD_MAPPINGS is None:
        mappings_path = Path(__file__).parent.parent.parent / "data" / "keyword_mappings.json"
        try:
            with open(mappings_path, "r", encoding="utf-8") as f:
                _KEYWORD_MAPPINGS = json.load(f)
        except Exception:
            _KEYWORD_MAPPINGS = {"article_keywords": {}, "guide_keywords": {}}
    return _KEYWORD_MAPPINGS


def match_articles_by_keywords(scenario_text: str) -> list[str]:
    """시나리오 텍스트에서 키워드 매핑으로 법조항 번호 반환"""
    mappings = _load_keyword_mappings()
    matched = []
    text_lower = scenario_text.lower()
    for art_num, info in mappings.get("article_keywords", {}).items():
        score = 0
        for kw in info.get("keywords", []):
            if kw in text_lower:
                score += 1
        for phrase in info.get("phrases", []):
            if phrase in text_lower:
                score += 2
        if score >= 1:
            matched.append((art_num, score))
    matched.sort(key=lambda x: x[1], reverse=True)
    return [art for art, _ in matched]


def match_guides_by_keywords(scenario_text: str) -> list[dict]:
    """시나리오 텍스트에서 키워드 매핑으로 KOSHA 가이드 코드 반환
    phrases 매칭 시 score+3 가산 (더 정밀한 매칭)
    """
    mappings = _load_keyword_mappings()
    matched = []
    text_lower = scenario_text.lower()
    for guide_code, info in mappings.get("guide_keywords", {}).items():
        score = 0
        for kw in info.get("keywords", []):
            if kw in text_lower:
                score += 1
        # phrases 매칭: 다어절 정확 매칭은 score+3 보너스
        for phrase in info.get("phrases", []):
            if phrase in text_lower:
                score += 3
        if score >= 1:
            matched.append({
                "guide_code": guide_code,
                "title": info.get("title", ""),
                "classification": info.get("classification", ""),
                "score": score,
            })
    matched.sort(key=lambda x: x["score"], reverse=True)
    return matched


class AnalysisService:
    async def analyze_image(
        self,
        db: Session,
        image_base64: str,
        filename: str,
        workplace_type: Optional[str] = None,
        additional_context: Optional[str] = None
    ) -> AnalysisResponse:
        """이미지 기반 위험요소 분석"""
        try:
            result = await openai_client.analyze_image(
                image_base64=image_base64,
                workplace_type=workplace_type,
                additional_context=additional_context
            )
        except Exception as e:
            raise OpenAIAPIError(f"AI 분석 실패: {str(e)}")

        return await self._create_response(
            db=db,
            result=result,
            analysis_type="image",
            input_preview=filename
        )

    async def analyze_text(
        self,
        db: Session,
        description: str,
        workplace_type: Optional[str] = None,
        industry_sector: Optional[str] = None
    ) -> AnalysisResponse:
        """텍스트 기반 위험요소 분석"""
        try:
            result = await openai_client.analyze_text(
                description=description,
                workplace_type=workplace_type,
                industry_sector=industry_sector
            )
        except Exception as e:
            raise OpenAIAPIError(f"AI 분석 실패: {str(e)}")

        # 입력 미리보기 (최대 100자)
        input_preview = description[:100] + "..." if len(description) > 100 else description

        return await self._create_response(
            db=db,
            result=result,
            analysis_type="text",
            input_preview=input_preview,
            full_description=description
        )

    # category_code → HazardCategory 매핑
    CATEGORY_MAP = {
        "FALL": "physical",
        "COLLISION": "physical",
        "CRUSH": "physical",
        "CUT": "physical",
        "FALLING_OBJECT": "physical",
        "SLIP": "physical",
        "PHYSICAL": "physical",
        "CHEMICAL": "chemical",
        "FIRE_EXPLOSION": "chemical",
        "CORROSION": "chemical",
        "TOXIC": "chemical",
        "ELECTRIC": "electrical",
        "ELECTRICAL": "electrical",
        "ARC_FLASH": "electrical",
        "ERGONOMIC": "ergonomic",
        "REPETITIVE": "ergonomic",
        "HEAVY_LIFTING": "ergonomic",
        "POSTURE": "ergonomic",
        "NOISE": "environmental",
        "TEMPERATURE": "environmental",
        "LIGHTING": "environmental",
        "ENVIRONMENTAL": "environmental",
        "BIOLOGICAL": "biological",
    }

    def _map_category(self, category_code: str) -> str:
        """category_code를 HazardCategory 값으로 변환"""
        return self.CATEGORY_MAP.get(category_code.upper(), "physical")

    def _derive_overall_risk_level(self, risks: list) -> str:
        """risks의 최고 severity에서 overall_risk_level 도출"""
        severity_priority = {"HIGH": "high", "MEDIUM": "medium", "LOW": "low"}
        severity_order = ["HIGH", "MEDIUM", "LOW"]
        for sev in severity_order:
            if any(r.get("severity") == sev for r in risks):
                return severity_priority[sev]
        return "medium"

    async def _create_response(
        self,
        db: Session,
        result: dict,
        analysis_type: str,
        input_preview: str,
        full_description: str = None
    ) -> AnalysisResponse:
        """GPT 분석 결과를 응답 형식으로 변환하고 DB에 저장

        v2.1: Phase 1+2 개선사항 통합
        - GPT related_article_hints 활용
        - LLM 쿼리 재작성
        - 카테고리 하드필터링
        - 형태소 분석 키워드 추출
        - LLM 재랭킹
        """
        analysis_id = str(uuid.uuid4())
        analyzed_at = datetime.now()

        # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
        # [Phase 3] Dual-Track: Track A (자유) + Track B (faceted)
        # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
        gpt_free_observations = []
        canonical_hazards = None
        code_gap_warnings = []
        penalties_list = []
        faceted_ci_data = []

        try:
            # Track A: 자유 분류 수집
            for fh in result.get("free_hazards", []):
                gpt_free_observations.append(GptFreeObservation(
                    label=fh.get("label", ""),
                    description=fh.get("description", ""),
                    confidence=fh.get("confidence", 0),
                    visual_evidence=fh.get("visual_evidence"),
                    severity=fh.get("severity", "MEDIUM"),
                ))

            # Track B: Faceted 코드 정규화 → 규칙 엔진
            gpt_faceted = result.get("faceted_hazards", {})
            context_text = " ".join(
                fh.get("description", "") for fh in result.get("free_hazards", [])
            ) + " " + (full_description or input_preview or "")

            normalized = normalize_faceted_hazards(gpt_faceted, context_text)
            canonical = hazard_rule_engine.apply_rules(normalized, db)

            canonical_hazards = FacetedHazardCodes(
                accident_types=canonical["accident_types"],
                hazardous_agents=canonical["hazardous_agents"],
                work_contexts=canonical["work_contexts"],
                applied_rules=canonical["applied_rules"],
                confidence=canonical["confidence"],
            )

            logger.warning(
                f"[Phase3] Canonical: AT={canonical['accident_types']}, "
                f"AG={canonical['hazardous_agents']}, WC={canonical['work_contexts']}"
            )

            # Divergence detection
            divergences = detect_divergence(
                result.get("free_hazards", []),
                canonical,
                gpt_faceted.get("forced_fit_notes", []),
            )
            for d in divergences:
                code_gap_warnings.append(CodeGapWarning(
                    gap_type=d["gap_type"],
                    gpt_free_label=d.get("gpt_free_label"),
                    description=d.get("description", ""),
                ))

            # Gap DB 저장
            if divergences:
                try:
                    save_gaps_to_db(db, divergences, analysis_id)
                except Exception as e:
                    logger.warning(f"Gap DB 저장 실패: {e}")

            # Faceted SR → CI → Penalty 조회
            sr_results = hazard_rule_engine.query_sr_for_facets(
                db,
                canonical["accident_types"],
                canonical["hazardous_agents"],
                canonical["work_contexts"],
            )
            sr_ids = [sr["identifier"] for sr in sr_results]

            # [Phase 5] SPARQL enrichment (Fuseki 추론 보강)
            sparql_enrichment_data = None
            try:
                sparql_enrichment_data = await hazard_rule_engine.enrich_sr_with_sparql(
                    sr_results,
                    canonical["accident_types"],
                    canonical["hazardous_agents"],
                    canonical["work_contexts"],
                )
                # SPARQL로 발견된 추가 SR을 sr_ids에 병합
                if sparql_enrichment_data:
                    for co_sr in sparql_enrichment_data.get("co_applicable_srs", []):
                        co_id = co_sr.get("sr_id")
                        if co_id and co_id not in sr_ids:
                            sr_ids.append(co_id)
            except Exception as e:
                logger.warning(f"[Phase5] SPARQL enrichment failed (PG-only fallback): {e}")

            # Faceted CI 조회 (Phase 4: 결정론적 체크리스트)
            faceted_ci_data = hazard_rule_engine.get_checklist_from_srs(db, sr_ids, limit=30)

            # [Phase 6] SR→CI→Guide 역추적으로 KOSHA Guide 후보 확보
            sr_linked_guides = hazard_rule_engine.get_guides_from_srs(db, sr_ids, limit=5)
            if sr_linked_guides:
                logger.warning(f"[Phase6] SR→CI→Guide: {[g['guide_code'] for g in sr_linked_guides]}")

            # Penalty 조회
            penalty_data = hazard_rule_engine.get_penalties_for_srs(db, sr_ids)
            for p in penalty_data:
                penalties_list.append(PenaltyInfo(
                    article_code=p["article_code"],
                    title=p["title"],
                    criminal_employer_penalty=p.get("criminal_employer_penalty"),
                    criminal_death_penalty=p.get("criminal_death_penalty"),
                    admin_max_fine=p.get("admin_max_fine"),
                ))

            # SR→Article 매핑으로 CI에 법적 근거 연결
            sr_article_map = {}  # sr_id → article_code
            for sr in sr_results:
                sid = sr["identifier"]
                for p in penalty_data:
                    sr_article_map[sid] = p["article_code"]
                    break  # 첫 번째 매핑만

        except Exception as e:
            logger.warning(f"[Phase3] Dual-Track 처리 실패 (기존 흐름 유지): {e}")

        # risks → Hazards 변환
        hazards = []
        hazard_categories = []
        hazard_codes_raw = []  # GPT 원본 category_code (서브카테고리)
        for r in result.get("risks", []):
            category = self._map_category(r.get("category_code", "PHYSICAL"))
            hazard_categories.append(category)
            hazard_codes_raw.append(r.get("category_code", "PHYSICAL").upper())
            hazards.append(Hazard(
                id=str(uuid.uuid4()),
                category=HazardCategory(category) if category in [e.value for e in HazardCategory] else HazardCategory.PHYSICAL,
                name=r.get("category_name", ""),
                description=r.get("description", ""),
                risk_level=RiskLevel(r.get("severity", "MEDIUM").lower()),
                location=r.get("location"),
                potential_consequences=[r.get("description", "")],
                preventive_measures=r.get("recommendations", []),
                legal_reference=None
            ))

        # immediate_actions → Checklist 변환
        checklist_items = []
        for i, action in enumerate(result.get("immediate_actions", []), start=1):
            checklist_items.append(ChecklistItem(
                id=str(uuid.uuid4()),
                category="즉시 조치",
                item=action,
                description=None,
                priority=i,
                is_mandatory=True,
                source_type="gpt",
                source_ref=None,
            ))

        # checklist는 norm 기반 항목 추가 후 아래에서 최종 생성
        gpt_checklist_items = checklist_items

        resources = []
        hazard_descs = [r.get("description", "") for r in result.get("risks", [])]

        # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
        # [Phase 0] 키워드 매핑 테이블 직접 매칭
        # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
        # full_description이 있으면 전체 텍스트 사용 (100자 제한 제거)
        full_text = full_description or input_preview or ""
        scenario_text = " ".join(hazard_descs) + " " + full_text
        kw_matched_articles = match_articles_by_keywords(scenario_text)
        kw_matched_guides = match_guides_by_keywords(scenario_text)
        if kw_matched_articles:
            logger.warning(f"[Phase0] 키워드매핑 법조항: {kw_matched_articles}")
        if kw_matched_guides:
            logger.warning(f"[Phase0] 키워드매핑 가이드: {[g['guide_code'] for g in kw_matched_guides]}")

        # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
        # [Phase 1-A] GPT related_article_hints 수집
        # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
        gpt_article_hints = {}  # article_number → reason
        for hint in result.get("related_article_hints", []):
            art_num = hint.get("article_number", "")
            if art_num:
                gpt_article_hints[art_num] = hint.get("reason", "")
        # 키워드 매핑 결과를 GPT 힌트에 병합 (GPT가 놓친 것 보강)
        for art_num in kw_matched_articles:
            if art_num not in gpt_article_hints:
                gpt_article_hints[art_num] = "키워드 매핑 자동 매칭"
        if gpt_article_hints:
            logger.warning(f"[Phase1-A] GPT+키워드 법조항 추천: {list(gpt_article_hints.keys())}")

        # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
        # [Phase 2-C] LLM 쿼리 재작성 (위험요소 설명 → 법률 키워드)
        # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
        enhanced_query = None
        try:
            enhanced_query = await rewrite_queries_batch(hazard_descs)
            logger.warning(f"[Phase2-C] 재작성 쿼리: {enhanced_query}")
        except Exception as e:
            logger.warning(f"쿼리 재작성 실패: {e}")

        # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
        # [Phase 2-E] 형태소 분석 키워드 추출 (가이드 검색용)
        # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
        guide_keywords = result.get("recommended_guide_keywords", [])[:5]
        logger.warning(f"[KOSHA] GPT 키워드: {guide_keywords}")

        # 형태소 분석으로 키워드 보충
        morpheme_keywords = extract_keywords_for_search(hazard_descs)
        effective_keywords = guide_keywords if guide_keywords else morpheme_keywords[:7]
        if guide_keywords and morpheme_keywords:
            # GPT 키워드 + 형태소 키워드 병합 (중복 제거)
            seen = set(guide_keywords)
            for mk in morpheme_keywords:
                if mk not in seen:
                    effective_keywords.append(mk)
                    seen.add(mk)
            effective_keywords = effective_keywords[:10]
        logger.warning(f"[Phase2-E] 통합 키워드: {effective_keywords}")

        # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
        # KOSHA GUIDE 검색 (기존 3-Path + 개선된 키워드 + 분류 라우팅)
        # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
        related_guides = []
        try:
            guide_results_map = {}  # guide_code → dict

            # [Phase 0-B] 분류 사전 라우팅: 시나리오 키워드로 분류 예측
            from app.services.guide_service import predict_classifications
            predicted_cls = predict_classifications(scenario_text)
            if predicted_cls:
                logger.warning(f"[KOSHA] 분류 예측: {predicted_cls}")

            # Path C: 키워드로 타이틀 직접 매칭 (형태소 분석 키워드 포함)
            path_c = guide_service.search_guides_by_title_keywords(
                db=db,
                keywords=effective_keywords,
                n_results=5,
                exclude_codes=[],
            )
            for g in path_c:
                guide_results_map[g["guide_code"]] = g
            logger.warning(f"[KOSHA] Path C (타이틀): {len(path_c)}건 ({[g['guide_code'] for g in path_c]})")

            # Path B: 벡터검색 (재작성된 쿼리 사용)
            search_descs = hazard_descs
            search_kw = guide_keywords if guide_keywords else None
            if enhanced_query:
                # 재작성된 쿼리를 설명에 추가하여 검색 품질 향상
                search_descs = [enhanced_query] + hazard_descs

            path_b = guide_service.search_guides_by_description(
                db=db,
                hazard_descriptions=search_descs,
                guide_keywords=search_kw,
                n_results=5,
                exclude_codes=list(guide_results_map.keys()),
            )
            for g in path_b:
                if g["guide_code"] not in guide_results_map:
                    guide_results_map[g["guide_code"]] = g
            logger.warning(f"[KOSHA] Path B (벡터): {len(path_b)}건 ({[g['guide_code'] for g in path_b]})")

            # 시맨틱 매핑 부스트 조회
            semantic_boost = {}
            try:
                semantic_boost = ontology_service.get_semantic_boost_for_guides(
                    db, list(guide_results_map.keys())
                )
            except Exception as e:
                logger.warning(f"시맨틱 부스트 조회 실패: {e}")

            # 키워드 매핑으로 직접 매칭된 가이드를 결과에 주입 (또는 기존 점수 부스트)
            for kw_guide in kw_matched_guides:
                code = kw_guide["guide_code"]
                raw_score = kw_guide["score"]
                if code in guide_results_map:
                    # 이미 다른 경로로 발견됨 → 키워드 매핑 보너스 가산
                    kw_boost_score = min(0.97, 0.80 + raw_score * 0.04)
                    if kw_boost_score > guide_results_map[code]["relevance_score"]:
                        guide_results_map[code]["relevance_score"] = kw_boost_score
                    guide_results_map[code]["mapping_type"] = "keyword_match"
                    guide_results_map[code]["kw_raw_score"] = raw_score
                    logger.warning(f"[Phase0] 키워드매핑 점수 부스트: {code} → raw={raw_score}")
                if code not in guide_results_map:
                    # DB에서 가이드 정보 조회 (PG)
                    from app.db.models import PgKoshaGuide, PgChecklistItem
                    guide_row = db.query(PgKoshaGuide).filter(PgKoshaGuide.guide_code == code).first()
                    if guide_row:
                        ci_rows = (
                            db.query(PgChecklistItem)
                            .filter(PgChecklistItem.source_guide == code)
                            .limit(2)
                            .all()
                        )
                        guide_results_map[code] = {
                            "guide_code": code,
                            "title": guide_row.title,
                            "classification": guide_row.domain,
                            "relevant_sections": [
                                {
                                    "section_title": ci.source_section or "",
                                    "excerpt": ci.text[:200] if ci.text else "",
                                    "section_type": "checklist",
                                }
                                for ci in ci_rows
                            ] if ci_rows else [],
                            "relevance_score": min(0.97, 0.80 + raw_score * 0.04),
                            "mapping_type": "keyword_match",
                            "kw_raw_score": raw_score,
                        }
                        logger.warning(f"[Phase0] 키워드매핑 가이드 주입: {code}")

            # [Phase 6] SR→CI→Guide 결과 주입 (온톨로지 직접 연결)
            for slg in sr_linked_guides:
                code = slg["guide_code"]
                if code not in guide_results_map:
                    guide_results_map[code] = slg
                    logger.warning(f"[Phase6] SR→CI→Guide 주입: {code} (CI {slg.get('ci_hit_count', 0)}건)")
                else:
                    # 이미 있으면 점수 부스트
                    existing_score = guide_results_map[code]["relevance_score"]
                    guide_results_map[code]["relevance_score"] = min(0.99, existing_score + 0.1)
                    guide_results_map[code]["mapping_type"] = "sr_ci_link"

            # Re-rank: effective_keywords + 시맨틱 부스트 + 분류 라우팅 기반 점수 조정
            for code, g in guide_results_map.items():
                title = g.get("title", "")
                keyword_hits = sum(1 for kw in effective_keywords if kw in title) if effective_keywords else 0

                if keyword_hits > 0:
                    boost = min(0.35, keyword_hits * 0.15)
                    g["relevance_score"] = min(0.99, g["relevance_score"] + boost)
                elif g.get("mapping_type") == "explicit":
                    g["relevance_score"] = g["relevance_score"] * 0.4

                sm_boost = semantic_boost.get(code, 0.0)
                if sm_boost > 0:
                    g["relevance_score"] = min(0.99, g["relevance_score"] + sm_boost)

                # 분류 사전 라우팅 부스트: 예측된 분류와 일치하면 가산
                guide_cls = g.get("classification", "")
                if predicted_cls and guide_cls in predicted_cls:
                    cls_rank = predicted_cls.index(guide_cls)
                    cls_boost = 0.08 - cls_rank * 0.02  # 1st: +0.08, 2nd: +0.06, 3rd: +0.04
                    g["relevance_score"] = min(0.99, g["relevance_score"] + cls_boost)

                # 키워드 매핑 가이드: raw_score 비례 점수 보장 (GPT 비결정성 대비)
                if g.get("mapping_type") == "keyword_match":
                    raw = g.get("kw_raw_score", 1)
                    if raw >= 4:  # 강력한 매칭 (2+ 키워드 또는 1+ phrase)
                        floor = 0.995
                    elif raw >= 2:
                        floor = 0.98
                    else:
                        floor = 0.96
                    g["relevance_score"] = max(g["relevance_score"], floor)

            # 점수 순 정렬, 최대 5개
            sorted_guides = sorted(
                guide_results_map.values(),
                key=lambda x: x["relevance_score"],
                reverse=True,
            )[:5]

            # 각 KOSHA GUIDE에 매핑된 법조항 추가 (역매핑)
            guide_codes = [g["guide_code"] for g in sorted_guides]
            guide_article_map = guide_service.get_mapped_articles_for_guides(db, guide_codes)

            for g in sorted_guides:
                mapped_refs = guide_article_map.get(g["guide_code"], [])
                enriched_refs = []
                for ref in mapped_refs:
                    article_num = ref["article_number"]
                    detail = article_service._find_article_by_number(article_num)
                    if detail:
                        enriched_refs.append({
                            "article_number": detail["article_number"],
                            "title": detail.get("title", ""),
                            "content": detail.get("content", ""),
                            "chapter": detail.get("chapter", ""),
                            "part": detail.get("part", ""),
                        })
                    else:
                        enriched_refs.append(ref)
                g["mapped_articles"] = enriched_refs

            related_guides = [GuideMatch(**g) for g in sorted_guides]

        except Exception as e:
            logger.warning(f"KOSHA GUIDE 검색 실패 (무시하고 계속): {e}")

        # overall_risk_level
        overall_risk_level = self._derive_overall_risk_level(result.get("risks", []))
        summary = result.get("overall_assessment", "")
        recommendations = result.get("immediate_actions", [])

        # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
        # 온톨로지 법조항 매칭 (개선: GPT 힌트 + 카테고리 필터 + 재작성 쿼리)
        # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
        norm_context_list = []
        try:
            # [Phase 1-A] GPT 추천 법조항을 우선 매칭 시도
            gpt_norm_contexts = []
            if gpt_article_hints:
                for art_num, reason in gpt_article_hints.items():
                    # 먼저 온톨로지(norm_statements)에서 조회
                    art_norms = ontology_service.get_article_norms(db, art_num)
                    if art_norms and art_norms.get("total_norms", 0) > 0:
                        art_norms["gpt_reason"] = reason  # GPT 추천 보너스 유지
                        gpt_norm_contexts.append(art_norms)
                    else:
                        # norm_statements가 없으면 ChromaDB에서 직접 조회
                        detail = article_service._find_article_by_number(art_num)
                        if detail:
                            gpt_norm_contexts.append({
                                "article_number": detail["article_number"],
                                "article_title": detail.get("title", ""),
                                "total_norms": 0,
                                "norms": [],
                                "linked_guides": [],
                                "gpt_reason": reason,
                            })

            # [Phase 1-B + 2-C] 카테고리 필터링 + 재작성 쿼리로 벡터검색
            search_query = enhanced_query or " ".join(hazard_descs)[:500]
            filtered_articles = article_service.search_articles_with_filter(
                query_text=search_query,
                hazard_categories=hazard_categories,
                n_results=20,
                min_score=0.42,
            )

            # 기존 온톨로지 매칭도 병행
            raw_norms = ontology_service.find_related_articles_for_hazards(
                db, hazard_descs, hazard_categories
            )

            # 결과 통합: GPT 힌트 (최우선) → 필터링 검색 → 기존 온톨로지
            seen_articles = set()
            combined_norms = []

            # 1순위: GPT 추천 법조항
            for nc in gpt_norm_contexts:
                art_num = nc.get("article_number", "")
                if art_num and art_num not in seen_articles:
                    seen_articles.add(art_num)
                    combined_norms.append(nc)

            # 2순위: 기존 온톨로지 매칭 (벡터+카테고리)
            for nc in raw_norms:
                art_num = nc.get("article_number", "")
                if art_num and art_num not in seen_articles:
                    seen_articles.add(art_num)
                    combined_norms.append(nc)

            # 3순위: 필터링 검색 결과 (벡터검색 유사도 순)
            for fa in filtered_articles:
                art_num = fa.get("article_number", "")
                if art_num and art_num not in seen_articles:
                    art_norms = ontology_service.get_article_norms(db, art_num)
                    if art_norms and art_norms.get("total_norms", 0) > 0:
                        seen_articles.add(art_num)
                        combined_norms.append(art_norms)
                    else:
                        # norm_statements 없어도 ChromaDB 데이터로 포함
                        seen_articles.add(art_num)
                        combined_norms.append({
                            "article_number": art_num,
                            "article_title": fa.get("title", ""),
                            "total_norms": 0,
                            "norms": [],
                            "linked_guides": [],
                            "vector_score": fa.get("score", 0),
                        })

            # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
            # [Phase 2-D] LLM 재랭킹: 통합된 법조항 후보를 의미적으로 재평가
            # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
            if len(combined_norms) > 3:
                rerank_candidates = []
                for nc in combined_norms[:15]:
                    art_num = nc.get("article_number", "")
                    art_title = nc.get("article_title", "") or ""
                    norm_texts = [n.get("full_text", "")[:100] for n in nc.get("norms", [])[:2]]
                    rerank_candidates.append({
                        "article_number": art_num,
                        "title": art_title,
                        "content": " ".join(norm_texts),
                        "original_score": 0.8 if art_num in gpt_article_hints else 0.6,
                        "_norm_data": nc,
                    })

                try:
                    reranked = await rerank_results(hazard_descs, rerank_candidates)
                    combined_norms = [c["_norm_data"] for c in reranked if "_norm_data" in c]
                    logger.warning(f"[Phase2-D] 재랭킹 결과: {[c.get('article_number') for c in combined_norms[:5]]}")
                except Exception as e:
                    logger.warning(f"재랭킹 실패 (원본 유지): {e}")

            # NormContext 생성 (최대 10개)
            for nc in combined_norms[:10]:
                norms_data = nc.get("norms", [])
                guides_data = nc.get("linked_guides", [])
                norm_context_list.append(NormContext(
                    article_number=nc.get("article_number", ""),
                    article_title=nc.get("article_title"),
                    norms=[NormSummary(**n) for n in norms_data] if norms_data else [],
                    linked_guides=[LinkedGuideSummary(**g) for g in guides_data] if guides_data else [],
                ))

            # Hazard.legal_reference + related_norms 채우기
            for hazard in hazards:
                best = self._find_best_norm_for_hazard(hazard, combined_norms)
                if best:
                    hazard.legal_reference = f"{best['article_number']} ({best.get('article_title', '')})"
                    hazard.related_norms = [
                        NormSummary(**n) for n in best.get("norms", [])[:3]
                    ]

        except Exception as e:
            logger.warning(f"온톨로지 매칭 실패 (무시하고 계속): {e}")
            db.rollback()

        # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
        # [Phase 4] Faceted CI → 결정론적 체크리스트 항목 변환
        # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
        faceted_checklist_items = []
        try:
            if faceted_ci_data:
                seen_ci_texts = set()
                for ci in faceted_ci_data:
                    ci_text = ci.get("text", "").strip()
                    if not ci_text or len(ci_text) < 5:
                        continue
                    # 중복 제거 (앞 30자 기준)
                    ci_key = ci_text[:30]
                    if ci_key in seen_ci_texts:
                        continue
                    seen_ci_texts.add(ci_key)

                    # binding_force에 따른 카테고리 결정
                    bf = (ci.get("binding_force") or "").upper()
                    if bf == "MANDATORY":
                        category = "결정론적 의무"
                        is_mandatory = True
                    else:
                        category = "결정론적 권장"
                        is_mandatory = False

                    faceted_checklist_items.append(ChecklistItem(
                        id=str(uuid.uuid4()),
                        category=category,
                        item=ci_text[:100] + ("..." if len(ci_text) > 100 else ""),
                        description=f"출처: {ci.get('source_guide', '')} / {ci.get('source_section', '')}",
                        priority=0,
                        is_mandatory=is_mandatory,
                        source_type="faceted_ci",
                        source_ref=ci.get("identifier", ""),
                    ))
                logger.warning(f"[Phase4] Faceted CI → 체크리스트: {len(faceted_checklist_items)}건")
        except Exception as e:
            logger.warning(f"Faceted CI 변환 실패: {e}")

        # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
        # 규범명제 → 체크리스트 변환 (법적 의무/금지 사항)
        # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
        norm_checklist_items = self._norms_to_checklist(norm_context_list, gpt_checklist_items)

        # 최종 체크리스트: 결정론적 의무 → 금지 사항 → 법적 의무 → 즉시 조치 순서
        all_checklist_items = []
        priority = 1
        # Phase 4: Faceted CI 결정론적 의무 (최우선)
        for item in faceted_checklist_items:
            if item.category == "결정론적 의무":
                item.priority = priority
                all_checklist_items.append(item)
                priority += 1
        for item in norm_checklist_items:
            if item.category == "금지 사항":
                item.priority = priority
                all_checklist_items.append(item)
                priority += 1
        for item in norm_checklist_items:
            if item.category == "법적 의무":
                item.priority = priority
                all_checklist_items.append(item)
                priority += 1
        # Phase 4: Faceted CI 결정론적 권장
        for item in faceted_checklist_items:
            if item.category == "결정론적 권장":
                item.priority = priority
                all_checklist_items.append(item)
                priority += 1
        for item in gpt_checklist_items:
            item.priority = priority
            all_checklist_items.append(item)
            priority += 1

        checklist = Checklist(
            title="안전점검 체크리스트",
            workplace_type=None,
            items=all_checklist_items,
        )

        # 관련 KOSHA 숏폼영상 (hazard_code 직접 매칭)
        try:
            resources = video_service.find_related_videos(
                db=db,
                hazard_codes=hazard_codes_raw,
                hazard_descriptions=[r.get("description", "") for r in result.get("risks", [])],
                max_results=5,
            )
        except Exception as e:
            logger.warning(f"숏폼영상 매칭 실패 (무시하고 계속): {e}")

        # 응답 생성
        response = AnalysisResponse(
            analysis_id=analysis_id,
            analysis_type=analysis_type,
            overall_risk_level=RiskLevel(overall_risk_level),
            summary=summary,
            hazards=hazards,
            checklist=checklist,
            resources=resources,
            related_guides=related_guides,
            norm_context=norm_context_list,
            recommendations=recommendations,
            analyzed_at=analyzed_at,
            # Phase 3: Dual-Track
            canonical_hazards=canonical_hazards,
            gpt_free_observations=gpt_free_observations,
            decision_type="deterministic_rule" if canonical_hazards else "embedding_fallback",
            code_gap_warnings=code_gap_warnings,
            penalties=penalties_list,
            # Phase 5: SPARQL enrichment
            sparql_enrichment=SparqlEnrichmentSummary(**sparql_enrichment_data) if sparql_enrichment_data else None,
        )

        # DB에 저장
        crud.create_analysis_record(
            db=db,
            analysis_id=analysis_id,
            analysis_type=analysis_type,
            overall_risk_level=overall_risk_level,
            summary=summary,
            input_preview=input_preview,
            result_json=json.loads(response.model_dump_json()),
            gpt_free_hazards=[o.model_dump(mode='json') for o in gpt_free_observations] if gpt_free_observations else None,
            coded_hazards=canonical_hazards.model_dump(mode='json') if canonical_hazards else None,
            divergence_report=[w.model_dump(mode='json') for w in code_gap_warnings] if code_gap_warnings else None,
        )

        return response


    def _find_best_norm_for_hazard(self, hazard: Hazard, norm_contexts: list) -> Optional[dict]:
        """Hazard에 가장 적합한 법조항+규범명제를 찾기

        우선순위:
        1. 위험요소 설명 키워드가 규범명제 텍스트에 포함된 법조항
        2. 카테고리 범위 내 법조항
        3. 첫 번째 법조항 (벡터 유사도 최상위)
        """
        if not norm_contexts:
            return None

        # 형태소 분석 키워드 추출 (개선: split 대신)
        from app.services.search_enhancer import extract_nouns
        keywords = extract_nouns(hazard.description)
        if not keywords:
            keywords = [w for w in hazard.description.split() if len(w) >= 2]

        # 1차: 키워드가 규범명제 텍스트 또는 조문 제목에 포함되는 법조항
        best_score = 0
        best_nc = None
        for nc in norm_contexts:
            score = 0
            all_norm_text = " ".join(n.get("full_text", "") for n in nc.get("norms", []))
            article_title = nc.get("article_title", "") or ""
            gpt_reason = nc.get("gpt_reason", "") or ""
            # 조문 제목 매칭은 가중치 2배 (가장 강한 시그널)
            for kw in keywords:
                if kw in article_title:
                    score += 2  # 제목 매칭: 가중치 높음
                elif kw in all_norm_text:
                    score += 1
                elif kw in gpt_reason:
                    score += 1
            # hazard name(카테고리명)이 제목에 직접 포함되면 추가 보너스
            hazard_name = hazard.name or ""
            if hazard_name and any(h in article_title for h in hazard_name.split("/")):
                score += 3
            # GPT 추천 조문은 기본 보너스
            if gpt_reason:
                score += 1
            if score > best_score:
                best_score = score
                best_nc = nc

        if best_nc and best_score >= 2:
            return best_nc

        # 2차: 첫 번째 반환 (벡터 유사도 순서 유지)
        return norm_contexts[0] if norm_contexts else None


    def _norms_to_checklist(
        self,
        norm_context_list: list,
        gpt_items: list,
    ) -> list:
        """규범명제(NormStatement)에서 법적 의무/금지 사항 체크리스트 항목 생성

        - PROHIBITION → "금지 사항" 카테고리
        - OBLIGATION  → "법적 의무" 카테고리
        - GPT 즉시조치와 중복되는 항목은 GPT 항목에 법적 근거를 병합하고 제거
        - 최대 5개 (PROHIBITION 우선)
        """
        from typing import List
        norm_items: List[ChecklistItem] = []

        # 1) 규범명제에서 OBLIGATION/PROHIBITION 추출
        candidates = []  # (legal_effect, action_text, article_number, full_text)
        for nc in norm_context_list:
            art_num = nc.article_number
            for norm in nc.norms:
                effect = (norm.legal_effect or "").upper()
                if effect not in ("OBLIGATION", "PROHIBITION"):
                    continue
                action = norm.action or ""
                full = norm.full_text or ""

                # 정의 조항 필터링 (체크리스트로 부적합)
                if action in ("정의한다", "정의하다", "규정하다", "규정한다"):
                    continue
                if any(full.lstrip().startswith(p) for p in ['"', '"', '\u201c', '\u201d', "「", "'"]):
                    continue  # 용어 정의 조항 ("~이란")
                if "이란 " in full[:40] or "란 " in full[:20]:
                    if any(w in full for w in ["말한다", "뜻한다", "의미한다", "같다", "다음"]):
                        continue  # "~이란 ~을 말한다" 패턴
                # 목록 참조 ("다음 각 호")나 하위 번호 항목 필터링
                if "다음 각 호" in action:
                    continue
                stripped_full = full.lstrip()
                if stripped_full and stripped_full[0].isdigit() and ". " in stripped_full[:5]:
                    continue  # "1. ~", "2. ~" 등 하위 항목

                candidates.append({
                    "effect": effect,
                    "action": action,
                    "article_number": art_num,
                    "full_text": full,
                })

        # PROHIBITION 우선 정렬
        candidates.sort(key=lambda c: (0 if c["effect"] == "PROHIBITION" else 1))

        # 2) 체크리스트 문장 생성 (템플릿 변환)
        seen_texts = set()  # 중복 방지
        for c in candidates:
            action = c["action"].strip()
            full = c["full_text"].strip()

            # 템플릿 변환
            if c["effect"] == "PROHIBITION":
                if action and len(action) <= 30:
                    # action이 이미 부정형이면 그대로 사용
                    if any(neg in action for neg in ["않을", "않는", "금지", "아니"]):
                        item_text = f"{action} 준수"
                    else:
                        item_text = f"{action} 금지 준수"
                else:
                    item_text = self._shorten_norm_text(full, "금지")
            else:  # OBLIGATION
                if action and len(action) <= 30:
                    item_text = f"{action} 여부 확인"
                else:
                    item_text = self._shorten_norm_text(full, "의무")

            if not item_text or len(item_text) < 4:
                continue

            # 동일 문장 중복 제거
            norm_key = item_text[:20]
            if norm_key in seen_texts:
                continue
            seen_texts.add(norm_key)

            category = "금지 사항" if c["effect"] == "PROHIBITION" else "법적 의무"
            source_type = "norm_prohibition" if c["effect"] == "PROHIBITION" else "norm_obligation"

            norm_items.append(ChecklistItem(
                id=str(uuid.uuid4()),
                category=category,
                item=item_text,
                description=full[:100] if full else None,
                priority=0,  # 나중에 재할당
                is_mandatory=True,
                source_type=source_type,
                source_ref=c["article_number"],
            ))

        # 3) GPT 즉시조치와 중복 제거 (키워드 2개 이상 겹침)
        norm_items = self._dedup_norm_vs_gpt(norm_items, gpt_items)

        # 4) 최대 5개 제한
        return norm_items[:5]

    def _shorten_norm_text(self, full_text: str, effect_type: str) -> str:
        """규범명제 원문을 체크리스트 어투로 축약"""
        if not full_text:
            return ""

        text = full_text.strip()

        # "사업주는 ~" 제거
        for prefix in ["사업주는 ", "사업주가 ", "근로자는 ", "근로자가 "]:
            if text.startswith(prefix):
                text = text[len(prefix):]
                break

        # 문장 끝 정리
        for suffix in [
            "하여야 한다.", "하여야 한다", "하여서는 아니 된다.", "하여서는 아니 된다",
            "아니 된다.", "아니 된다", "한다.", "한다",
        ]:
            if text.endswith(suffix):
                text = text[:-len(suffix)].strip()
                break

        # 너무 길면 50자로 자름
        if len(text) > 50:
            text = text[:50].rsplit(" ", 1)[0]

        if effect_type == "금지":
            return f"{text} 금지 준수" if text else ""
        else:
            return f"{text} 여부 확인" if text else ""

    def _dedup_norm_vs_gpt(
        self, norm_items: list, gpt_items: list
    ) -> list:
        """규범명제 체크리스트와 GPT 즉시조치 사이 중복 제거

        키워드 2개 이상 겹치면 중복으로 판단:
        - GPT 항목에 법적 근거(source_ref) 병합
        - 규범명제 항목은 제거
        """
        from app.services.search_enhancer import extract_nouns

        # GPT 항목별 키워드 추출
        gpt_keywords_list = []
        for gi in gpt_items:
            kws = extract_nouns(gi.item)
            if not kws:
                kws = [w for w in gi.item.split() if len(w) >= 2]
            gpt_keywords_list.append(set(kws))

        kept = []
        for ni in norm_items:
            norm_kws = extract_nouns(ni.item)
            if not norm_kws:
                norm_kws = [w for w in ni.item.split() if len(w) >= 2]
            norm_kws_set = set(norm_kws)

            is_dup = False
            for idx, gpt_kws in enumerate(gpt_keywords_list):
                overlap = norm_kws_set & gpt_kws
                if len(overlap) >= 2:
                    # GPT 항목에 법적 근거 병합
                    gpt_items[idx].source_type = ni.source_type
                    gpt_items[idx].source_ref = ni.source_ref
                    is_dup = True
                    break

            if not is_dup:
                kept.append(ni)

        return kept


analysis_service = AnalysisService()
