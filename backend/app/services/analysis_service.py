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
from app.models.analysis import AnalysisResponse, NormContext, LinkedGuideSummary
from app.models.guide import GuideMatch, GuideArticleRef
from app.models.hazard import Hazard, RiskLevel, HazardCategory, NormSummary
from app.models.checklist import Checklist, ChecklistItem
from app.db import crud
from app.utils.exceptions import OpenAIAPIError

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

        # risks → Hazards 변환
        hazards = []
        hazard_categories = []
        for r in result.get("risks", []):
            category = self._map_category(r.get("category_code", "PHYSICAL"))
            hazard_categories.append(category)
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
                is_mandatory=True
            ))

        checklist = Checklist(
            title="안전점검 체크리스트",
            workplace_type=None,
            items=checklist_items
        )

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
                    # DB에서 가이드 정보 조회
                    from app.db.models import KoshaGuide, GuideSection as GuideSectionModel
                    guide_row = db.query(KoshaGuide).filter(KoshaGuide.guide_code == code).first()
                    if guide_row:
                        sections = (
                            db.query(GuideSectionModel)
                            .filter(GuideSectionModel.guide_id == guide_row.id)
                            .filter(GuideSectionModel.section_type.in_(["standard", "procedure"]))
                            .order_by(GuideSectionModel.section_order)
                            .limit(2)
                            .all()
                        )
                        guide_results_map[code] = {
                            "guide_code": code,
                            "title": guide_row.title,
                            "classification": guide_row.classification,
                            "relevant_sections": [
                                {
                                    "section_title": s.section_title or "",
                                    "excerpt": s.body_text[:200] if s.body_text else "",
                                    "section_type": s.section_type or "standard",
                                }
                                for s in sections
                            ] if sections else [],
                            "relevance_score": min(0.97, 0.80 + raw_score * 0.04),
                            "mapping_type": "keyword_match",
                            "kw_raw_score": raw_score,
                        }
                        logger.warning(f"[Phase0] 키워드매핑 가이드 주입: {code}")

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
                            "content": detail.get("content", "")[:300],
                            "source_file": detail.get("source_file", ""),
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

        # 관련 KOSHA 숏폼영상 (3-Layer 매칭)
        try:
            norm_articles = [nc.article_number for nc in norm_context_list]
            guide_cls = list({g.classification for g in related_guides}) if related_guides else []

            resources = video_service.find_related_videos(
                db=db,
                hazard_descriptions=[r.get("description", "") for r in result.get("risks", [])],
                hazard_categories=hazard_categories,
                norm_articles=norm_articles,
                guide_classifications=guide_cls,
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
            analyzed_at=analyzed_at
        )

        # DB에 저장
        crud.create_analysis_record(
            db=db,
            analysis_id=analysis_id,
            analysis_type=analysis_type,
            overall_risk_level=overall_risk_level,
            summary=summary,
            input_preview=input_preview,
            result_json=response.model_dump()
        )

        return response


    # 카테고리별 법조항 범위 (_find_best_norm_for_hazard 폴백용)
    CATEGORY_ARTICLE_RANGE = {
        "physical": [(3, 70), (86, 224), (328, 419)],
        "chemical": [(225, 300), (420, 511)],
        "electrical": [(301, 327)],
        "ergonomic": [(656, 670)],
        "environmental": [(512, 521), (558, 617), (618, 644)],
        "biological": [(592, 604)],
    }

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


analysis_service = AnalysisService()
