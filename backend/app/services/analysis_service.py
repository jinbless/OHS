from typing import Optional
from datetime import datetime
import uuid
from sqlalchemy.orm import Session

import logging

from app.integrations.openai_client import openai_client
from app.services.resource_service import resource_service
from app.services.article_service import article_service
from app.services.guide_service import guide_service
from app.models.analysis import AnalysisResponse
from app.models.article import ArticleMatch
from app.models.guide import GuideMatch, GuideArticleRef
from app.models.hazard import Hazard, RiskLevel, HazardCategory
from app.models.checklist import Checklist, ChecklistItem
from app.db import crud
from app.utils.exceptions import OpenAIAPIError

logger = logging.getLogger(__name__)


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

        return self._create_response(
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

        return self._create_response(
            db=db,
            result=result,
            analysis_type="text",
            input_preview=input_preview
        )

    # GPT-5.2 category_code → HazardCategory 매핑
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
        """GPT-5.2 category_code를 HazardCategory 값으로 변환"""
        return self.CATEGORY_MAP.get(category_code.upper(), "physical")

    def _derive_overall_risk_level(self, risks: list) -> str:
        """risks의 최고 severity에서 overall_risk_level 도출"""
        severity_priority = {"HIGH": "high", "MEDIUM": "medium", "LOW": "low"}
        severity_order = ["HIGH", "MEDIUM", "LOW"]
        for sev in severity_order:
            if any(r.get("severity") == sev for r in risks):
                return severity_priority[sev]
        return "medium"

    def _create_response(
        self,
        db: Session,
        result: dict,
        analysis_type: str,
        input_preview: str
    ) -> AnalysisResponse:
        """GPT-5.2 분석 결과를 응답 형식으로 변환하고 DB에 저장"""
        analysis_id = str(uuid.uuid4())
        analyzed_at = datetime.now()

        # GPT-5.2 risks → Hazards 변환
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

        # GPT-5.2 immediate_actions → Checklist 변환
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

        # 관련 리소스 가져오기
        resources = resource_service.get_resources_by_categories(hazard_categories)

        # 관련 법조항 검색 (하이브리드 파이프라인 v2)
        related_articles = []
        try:
            if article_service.collection.count() > 0:
                hazard_dicts = [
                    {
                        "category_code": r.get("category_code", ""),
                        "name": r.get("category_name", ""),
                        "description": r.get("description", ""),
                    }
                    for r in result.get("risks", [])
                ]
                gpt_recommended = result.get("related_articles", [])
                article_results = article_service.hybrid_search_for_hazards(
                    hazards=hazard_dicts,
                    gpt_recommended_articles=gpt_recommended if gpt_recommended else None,
                )
                related_articles = [ArticleMatch(**a) for a in article_results]
        except Exception as e:
            logger.warning(f"법조항 검색 실패 (무시하고 계속): {e}")

        # 관련 KOSHA GUIDE 검색 (Dual-Path + 키워드 Re-rank)
        related_guides = []
        try:
            guide_results_map = {}  # guide_code → dict (중복 제거용)
            hazard_descs = [
                r.get("description", "") for r in result.get("risks", [])
            ]
            hazard_text = " ".join(hazard_descs)
            guide_keywords = result.get("recommended_guide_keywords", [])[:5]  # 최대 5개 (dilution 방지)
            logger.warning(f"[KOSHA] GPT 키워드: {guide_keywords}")

            # 키워드가 없으면 설명에서 자동 추출 (re-ranking용)
            effective_keywords = guide_keywords
            if not effective_keywords:
                effective_keywords = guide_service._extract_key_nouns(hazard_descs)
                logger.warning(f"[KOSHA] 자동추출 키워드: {effective_keywords}")

            # Path C: 키워드로 타이틀 직접 매칭 (결정론적, 가장 먼저)
            path_c = guide_service.search_guides_by_title_keywords(
                db=db,
                keywords=effective_keywords,
                n_results=5,
                exclude_codes=[],
            )
            for g in path_c:
                guide_results_map[g["guide_code"]] = g
            logger.warning(f"[KOSHA] Path C (타이틀): {len(path_c)}건 ({[g['guide_code'] for g in path_c]})")

            # Path B: 직접 벡터검색
            path_b = guide_service.search_guides_by_description(
                db=db,
                hazard_descriptions=hazard_descs,
                guide_keywords=guide_keywords if guide_keywords else None,
                n_results=5,
                exclude_codes=list(guide_results_map.keys()),
            )
            for g in path_b:
                if g["guide_code"] not in guide_results_map:
                    guide_results_map[g["guide_code"]] = g
            logger.warning(f"[KOSHA] Path B (벡터): {len(path_b)}건 ({[g['guide_code'] for g in path_b]})")

            # Path A: 법조항 매핑 기반 검색 (보조)
            if related_articles:
                article_nums = [a.article_number for a in related_articles]
                path_a = guide_service.search_guides_for_articles(
                    db=db,
                    article_numbers=article_nums,
                    hazard_description=hazard_text,
                    n_results=5,
                )
                for g in path_a:
                    if g["guide_code"] not in guide_results_map:
                        guide_results_map[g["guide_code"]] = g
                logger.warning(f"[KOSHA] Path A (법조항): {len(path_a)}건 ({[g['guide_code'] for g in path_a]})")

            # Re-rank: effective_keywords(GPT 또는 자동추출) + 핵심 명사 기반 점수 조정
            for code, g in guide_results_map.items():
                title = g.get("title", "")
                # 키워드 매칭 (가장 강한 시그널) - GPT 키워드든 자동추출이든
                keyword_hits = sum(1 for kw in effective_keywords if kw in title) if effective_keywords else 0

                if keyword_hits > 0:
                    boost = min(0.35, keyword_hits * 0.15)
                    g["relevance_score"] = min(0.99, g["relevance_score"] + boost)
                elif g.get("mapping_type") == "explicit":
                    # explicit 매핑이지만 키워드와 전혀 무관 → 강한 페널티
                    g["relevance_score"] = g["relevance_score"] * 0.4
                logger.warning(f"[KOSHA] Re-rank: {code} kw={keyword_hits} {g['relevance_score']:.3f} ({title[:30]})")

            # 점수 순 정렬, 최대 5개
            sorted_guides = sorted(
                guide_results_map.values(),
                key=lambda x: x["relevance_score"],
                reverse=True,
            )[:5]

            # 각 KOSHA GUIDE에 매핑된 법조항 추가 (역매핑)
            guide_codes = [g["guide_code"] for g in sorted_guides]
            guide_article_map = guide_service.get_mapped_articles_for_guides(db, guide_codes)

            # 가이드에 매핑된 법조항의 상세 정보를 article_service에서 조회
            guide_covered_articles = set()  # 가이드에서 이미 커버된 법조항
            for g in sorted_guides:
                mapped_refs = guide_article_map.get(g["guide_code"], [])
                enriched_refs = []
                for ref in mapped_refs:
                    article_num = ref["article_number"]
                    guide_covered_articles.add(article_num)
                    # ChromaDB에서 상세 정보 조회
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

            # 독립 검색 법조항에서 가이드에 이미 포함된 것 제외
            if guide_covered_articles and related_articles:
                related_articles = [
                    a for a in related_articles
                    if a.article_number not in guide_covered_articles
                ]

        except Exception as e:
            logger.warning(f"KOSHA GUIDE 검색 실패 (무시하고 계속): {e}")

        # overall_risk_level 도출
        overall_risk_level = self._derive_overall_risk_level(result.get("risks", []))

        # GPT-5.2 overall_assessment → summary
        summary = result.get("overall_assessment", "")

        # immediate_actions → recommendations
        recommendations = result.get("immediate_actions", [])

        # 응답 생성
        response = AnalysisResponse(
            analysis_id=analysis_id,
            analysis_type=analysis_type,
            overall_risk_level=RiskLevel(overall_risk_level),
            summary=summary,
            hazards=hazards,
            checklist=checklist,
            resources=resources,
            related_articles=related_articles,
            related_guides=related_guides,
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


analysis_service = AnalysisService()
