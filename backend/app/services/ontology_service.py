"""온톨로지 기반 매핑 서비스.

Plan Phase 1(규범명제 분해 + 관계유형 분류) + Phase 2(미매핑 자동 발견)를 구현.
"""
import re
import json
import logging
from typing import List, Optional, Dict

from sqlalchemy.orm import Session
from sqlalchemy import func as sa_func, distinct

from app.utils.text_utils import extract_article_number

from app.db.models import (
    NormStatement, SemanticMapping,
    RegGuideMapping, KoshaGuide, GuideSection,
)
from app.services.norm_extractor import norm_extractor
from app.services.article_service import article_service
from app.services.guide_service import guide_service, CLASSIFICATION_TO_ARTICLE_RANGE

logger = logging.getLogger(__name__)


class OntologyService:
    """온톨로지 기반 매핑 관리 서비스"""

    # ===================================================================
    #  Phase 1: 규범명제 분해 + 관계유형 분류
    # ===================================================================

    async def extract_all_norms(self, db: Session) -> dict:
        """전체 법조항 → 규범명제 분해 (일괄 실행)

        1. article_service에서 전체 법조항 텍스트 로드
        2. NormExtractor로 규범명제 추출
        3. norm_statements 테이블에 저장
        """
        # 이미 추출된 것 확인
        existing_count = db.query(NormStatement).count()
        if existing_count > 0:
            logger.info(f"이미 {existing_count}개 규범명제 존재. 증분 처리.")

        # 기존에 추출된 조항 번호
        existing_articles = set(
            row[0] for row in
            db.query(distinct(NormStatement.article_number)).all()
        )

        # 전체 법조항 로드
        articles = article_service.parse_all_pdfs()
        if not articles:
            return {"status": "error", "message": "법조항 데이터 없음"}

        # 미처리 조항만 필터
        to_process = [
            {"article_number": a.article_number, "content": a.content}
            for a in articles
            if a.article_number not in existing_articles
        ]

        if not to_process:
            return {
                "status": "completed",
                "total_articles": len(articles),
                "processed": 0,
                "total_norms_extracted": existing_count,
                "errors": [],
                "message": "모든 법조항 이미 처리됨",
            }

        logger.info(f"규범명제 추출 시작: {len(to_process)}개 법조항")

        # 배치 추출
        result = await norm_extractor.batch_extract(to_process)

        # DB 저장
        saved_count = 0
        for norm in result["norms"]:
            try:
                stmt = NormStatement(
                    article_number=norm["article_number"],
                    paragraph=norm.get("paragraph"),
                    statement_order=norm.get("statement_order", 1),
                    subject_role=norm.get("subject_role"),
                    action=norm.get("action"),
                    object=norm.get("object"),
                    condition_text=norm.get("condition_text"),
                    legal_effect=norm["legal_effect"],
                    effect_description=norm.get("effect_description"),
                    full_text=norm["full_text"],
                    norm_category=norm.get("norm_category"),
                )
                db.add(stmt)
                saved_count += 1

                if saved_count % 100 == 0:
                    db.commit()
            except Exception as e:
                logger.warning(f"규범명제 저장 실패: {e}")
                db.rollback()

        db.commit()
        logger.info(f"규범명제 추출 완료: {saved_count}개 저장")

        return {
            "status": "completed",
            "total_articles": len(articles),
            "processed": result["processed"],
            "total_norms_extracted": saved_count + existing_count,
            "errors": result["errors"],
        }

    async def classify_existing_mappings(self, db: Session) -> dict:
        """기존 explicit 매핑의 관계 유형 자동 분류

        1. reg_guide_mapping에서 전체 매핑 로드
        2. 법조항 + 가이드 정보 기반 관계 유형 결정
        3. semantic_mappings 테이블에 저장
        """
        # 이미 분류된 매핑 확인
        existing_sm = set(
            (row.source_id, row.target_id)
            for row in db.query(SemanticMapping).filter(
                SemanticMapping.discovery_method == "explicit"
            ).all()
        )

        # 기존 매핑 로드
        mappings = (
            db.query(RegGuideMapping, KoshaGuide)
            .join(KoshaGuide, RegGuideMapping.guide_id == KoshaGuide.id)
            .all()
        )

        classified = 0
        by_type = {}

        for mapping, guide in mappings:
            key = (mapping.article_number, str(guide.id))
            if key in existing_sm:
                continue

            relation = self._determine_relation_type(mapping, guide)
            by_type[relation] = by_type.get(relation, 0) + 1

            sm = SemanticMapping(
                source_type="article",
                source_id=mapping.article_number,
                target_type="guide",
                target_id=str(guide.id),
                relation_type=relation,
                relation_detail=f"{guide.guide_code} ({guide.title})",
                confidence=mapping.relevance_score or 0.95,
                discovery_method="explicit",
                discovery_tier="A",
            )
            db.add(sm)
            classified += 1

            if classified % 200 == 0:
                db.commit()

        db.commit()
        logger.info(f"매핑 관계 분류 완료: {classified}건")

        return {
            "status": "completed",
            "total_mappings": len(mappings),
            "classified": classified,
            "by_relation_type": by_type,
        }

    def _determine_relation_type(self, mapping: RegGuideMapping, guide: KoshaGuide) -> str:
        """법조항-가이드 관계 유형 자동 결정

        우선순위: SPECIFIES_CRITERIA > SPECIFIES_METHOD > IMPLEMENTS > SUPPLEMENTS
        """
        title = (guide.title or "")
        title_lower = title.lower()

        # 1. 정량 키워드 포함 → SPECIFIES_CRITERIA (가장 구체적인 관계)
        quant_keywords = [
            "mm", "cm", "kg", "°c", "ppm", "%", "db", "lux",
            "이상", "이하", "미만", "초과", "기준", "허용농도",
            "측정", "시험", "검사방법", "규격", "성능",
        ]
        if any(kw in title_lower for kw in quant_keywords):
            return "SPECIFIES_CRITERIA"

        # 2. classification과 법조항 범위 매칭 → SPECIFIES_METHOD
        article_num = self._extract_article_num(mapping.article_number)
        if article_num and guide.classification in CLASSIFICATION_TO_ARTICLE_RANGE:
            range_ = CLASSIFICATION_TO_ARTICLE_RANGE[guide.classification]
            if range_ and range_[0] <= article_num <= range_[1]:
                return "SPECIFIES_METHOD"

        # 3. 가이드 관련법규에 법조항 직접 인용 → IMPLEMENTS
        if guide.related_regulations:
            try:
                regs = json.loads(guide.related_regulations)
                if mapping.article_number in regs:
                    return "IMPLEMENTS"
            except (json.JSONDecodeError, Exception):
                pass

        # 4. 기본값
        return "SUPPLEMENTS"

    def _extract_article_num(self, article_number: str) -> Optional[int]:
        """'제42조' → 42"""
        result = extract_article_number(article_number)
        return result if result != 0 else None

    # ===================================================================
    #  Phase 2: 미매핑 자동 발견
    # ===================================================================

    async def discover_unmapped_articles(self, db: Session) -> dict:
        """미매핑 법조항에 대해 가이드 후보 발견 (Tier F: 벡터 유사도)"""
        # 매핑된 법조항 번호
        mapped_articles = set(
            row[0] for row in
            db.query(distinct(RegGuideMapping.article_number)).all()
        )

        # 전체 법조항
        all_articles = article_service.parse_all_pdfs()
        unmapped = [a for a in all_articles if a.article_number not in mapped_articles]

        if not unmapped:
            return {"status": "completed", "new_mappings": 0, "message": "모든 법조항 매핑 완료"}

        logger.info(f"미매핑 법조항 {len(unmapped)}개 가이드 후보 발견 시작")

        new_mappings = 0
        if guide_service.collection.count() == 0:
            return {"status": "error", "message": "ChromaDB 가이드 인덱스 없음"}

        from openai import OpenAI
        openai_client = OpenAI(api_key=article_service._openai.api_key)

        for article in unmapped:
            try:
                query_text = f"{article.article_number} {article.title}\n{article.content[:500]}"

                response = openai_client.embeddings.create(
                    model="text-embedding-3-small",
                    input=[query_text],
                )
                query_embedding = response.data[0].embedding

                results = guide_service.collection.query(
                    query_embeddings=[query_embedding],
                    n_results=5,
                    include=["metadatas", "distances"],
                )

                if not results or not results["metadatas"] or not results["metadatas"][0]:
                    continue

                seen_guides = set()
                for i, meta in enumerate(results["metadatas"][0]):
                    distance = results["distances"][0][i]
                    confidence = round(1 - distance, 4)

                    if confidence < 0.65:
                        continue

                    guide_id = str(meta.get("guide_id", ""))
                    if not guide_id or guide_id in seen_guides:
                        continue
                    seen_guides.add(guide_id)

                    # 이미 존재하는지 체크 (동일 relation_type 포함)
                    exists = db.query(SemanticMapping).filter(
                        SemanticMapping.source_type == "article",
                        SemanticMapping.source_id == article.article_number,
                        SemanticMapping.target_type == "guide",
                        SemanticMapping.target_id == guide_id,
                        SemanticMapping.relation_type == "SPECIFIES_METHOD",
                    ).first()
                    if exists:
                        continue

                    sm = SemanticMapping(
                        source_type="article",
                        source_id=article.article_number,
                        target_type="guide",
                        target_id=guide_id,
                        relation_type="SPECIFIES_METHOD",
                        relation_detail=f"벡터유사도: {meta.get('guide_code', '')} ({meta.get('title', '')})",
                        confidence=confidence,
                        discovery_method="vector",
                        discovery_tier="F",
                    )
                    db.add(sm)
                    new_mappings += 1

            except Exception as e:
                logger.warning(f"{article.article_number} 벡터 검색 실패: {e}")
                continue

        db.commit()
        logger.info(f"미매핑 법조항 자동 발견 완료: {new_mappings}개 신규 매핑")

        return {
            "status": "completed",
            "total_unmapped": len(unmapped),
            "new_mappings": new_mappings,
        }

    async def discover_unmapped_guides(self, db: Session) -> dict:
        """미매핑 가이드에 대해 법조항 후보 발견 (Tier B+F: 키워드+벡터)"""
        # 매핑된 가이드 ID
        mapped_guide_ids = set(
            row[0] for row in
            db.query(distinct(RegGuideMapping.guide_id)).all()
        )
        # semantic_mappings에서도 확인
        sm_mapped_ids = set(
            row[0] for row in
            db.query(distinct(SemanticMapping.target_id))
            .filter(SemanticMapping.target_type == "guide")
            .all()
        )

        # 전체 가이드
        all_guides = db.query(KoshaGuide).all()
        unmapped = [
            g for g in all_guides
            if g.id not in mapped_guide_ids and str(g.id) not in sm_mapped_ids
        ]

        if not unmapped:
            return {"status": "completed", "new_mappings": 0, "message": "모든 가이드 매핑 완료"}

        logger.info(f"미매핑 가이드 {len(unmapped)}개 법조항 후보 발견 시작")

        # 전체 법조항 로드 (키워드 매칭용)
        all_articles = article_service.parse_all_pdfs()
        article_map = {a.article_number: a for a in all_articles}

        # 확대된 안전 키워드 사전 (28개 → 85개)
        safety_keywords = {
            # 사고유형
            "추락", "감전", "화재", "폭발", "질식", "전도", "협착", "절단",
            "충돌", "낙하", "비산", "붕괴", "도괴", "끼임", "말림", "침수",
            "넘어짐", "미끄러짐", "산소결핍", "중독", "화상",
            # 장소/설비
            "밀폐", "굴착", "크레인", "프레스", "컨베이어", "리프트", "보일러",
            "압력용기", "지게차", "곤돌라", "승강기", "엘리베이터", "에스컬레이터",
            "차량", "로봇", "용접", "도장", "건조", "세척", "선반", "연삭",
            "사다리", "비계", "거푸집", "터널", "교량", "철골", "옹벽",
            "해체", "관로", "배관", "덕트", "탱크", "저장", "운반",
            # 유해인자
            "유해물질", "석면", "소음", "진동", "방사선", "분진", "중량물",
            "유기화합물", "특별관리물질", "발암물질", "화학물질", "가스",
            "증기", "흄", "미스트", "고열", "저온", "고압", "전리방사선",
            "레이저", "자외선", "적외선", "소독", "살균",
            # 보호구/안전장치
            "보호구", "안전대", "안전모", "안전화", "방호장치", "안전밸브",
            "경보장치", "감지기", "환기", "배기", "국소배기",
            # 관리/절차
            "점검", "검사", "측정", "교육", "허가", "작업중지",
        }

        new_mappings = 0
        keyword_resolved = set()  # 키워드로 매핑된 가이드 ID

        for guide in unmapped:
            title = guide.title or ""

            # Tier B: 키워드 매칭
            matched_articles = []
            for kw in safety_keywords:
                if kw in title:
                    for art_num, art in article_map.items():
                        if kw in art.title or kw in art.content[:500]:
                            matched_articles.append((art_num, 0.7))

            # classification 범위 필터 (완화: range 없으면 전체 허용)
            range_ = CLASSIFICATION_TO_ARTICLE_RANGE.get(guide.classification)
            if range_:
                filtered = [
                    (num, score) for num, score in matched_articles
                    if self._extract_article_num(num) and
                    range_[0] <= self._extract_article_num(num) <= range_[1]
                ]
                # 범위 내 결과가 없으면 범위 필터 해제
                if not filtered and matched_articles:
                    filtered = matched_articles
                matched_articles = filtered

            # 중복 제거 + 상위 3개
            seen = set()
            unique_matches = []
            for num, score in matched_articles:
                if num not in seen:
                    seen.add(num)
                    unique_matches.append((num, score))
            unique_matches = unique_matches[:3]

            for article_num, score in unique_matches:
                exists = db.query(SemanticMapping).filter(
                    SemanticMapping.source_type == "article",
                    SemanticMapping.source_id == article_num,
                    SemanticMapping.target_type == "guide",
                    SemanticMapping.target_id == str(guide.id),
                    SemanticMapping.relation_type == "SPECIFIES_METHOD",
                ).first()
                if exists:
                    continue

                try:
                    sm = SemanticMapping(
                        source_type="article",
                        source_id=article_num,
                        target_type="guide",
                        target_id=str(guide.id),
                        relation_type="SPECIFIES_METHOD",
                        relation_detail=f"키워드매칭: {guide.guide_code} ({title})",
                        confidence=score,
                        discovery_method="keyword",
                        discovery_tier="B",
                    )
                    db.add(sm)
                    db.flush()
                    new_mappings += 1
                    keyword_resolved.add(guide.id)
                except Exception:
                    db.rollback()
                    continue

        db.commit()
        keyword_count = new_mappings
        logger.info(f"키워드 매칭 완료: {keyword_count}개 매핑")

        # Tier F: 벡터 유사도 (키워드 매칭 실패한 가이드 대상)
        still_unmapped = [g for g in unmapped if g.id not in keyword_resolved]

        if still_unmapped and article_service.collection.count() > 0:
            logger.info(f"벡터 검색 시작: {len(still_unmapped)}개 미매핑 가이드")

            from openai import OpenAI
            openai_client = OpenAI(api_key=article_service._openai.api_key)

            for guide in still_unmapped:
                try:
                    query_text = f"{guide.guide_code} {guide.title}"
                    response = openai_client.embeddings.create(
                        model="text-embedding-3-small",
                        input=[query_text],
                    )
                    query_embedding = response.data[0].embedding

                    results = article_service.collection.query(
                        query_embeddings=[query_embedding],
                        n_results=3,
                        include=["metadatas", "distances"],
                    )

                    if not results or not results["metadatas"] or not results["metadatas"][0]:
                        continue

                    seen_arts = set()
                    for i, meta in enumerate(results["metadatas"][0]):
                        distance = results["distances"][0][i]
                        confidence = round(1 - distance, 4)

                        if confidence < 0.55:
                            continue

                        art_num = meta.get("article_number", "")
                        if not art_num or art_num in seen_arts:
                            continue
                        seen_arts.add(art_num)

                        exists = db.query(SemanticMapping).filter(
                            SemanticMapping.source_type == "article",
                            SemanticMapping.source_id == art_num,
                            SemanticMapping.target_type == "guide",
                            SemanticMapping.target_id == str(guide.id),
                            SemanticMapping.relation_type == "SPECIFIES_METHOD",
                        ).first()
                        if exists:
                            continue

                        try:
                            sm = SemanticMapping(
                                source_type="article",
                                source_id=art_num,
                                target_type="guide",
                                target_id=str(guide.id),
                                relation_type="SPECIFIES_METHOD",
                                relation_detail=f"벡터유사도: {guide.guide_code} ({guide.title})",
                                confidence=confidence,
                                discovery_method="vector",
                                discovery_tier="F",
                            )
                            db.add(sm)
                            db.flush()
                            new_mappings += 1
                        except Exception:
                            db.rollback()
                            continue

                except Exception as e:
                    logger.warning(f"{guide.guide_code} 벡터 검색 실패: {e}")
                    continue

            db.commit()

        vector_count = new_mappings - keyword_count
        logger.info(f"미매핑 가이드 자동 발견 완료: 키워드 {keyword_count}건 + 벡터 {vector_count}건 = 총 {new_mappings}건")

        return {
            "status": "completed",
            "total_unmapped": len(unmapped),
            "new_mappings": new_mappings,
            "keyword_mappings": keyword_count,
            "vector_mappings": vector_count,
        }

    async def discover_cross_references(self, db: Session) -> dict:
        """법조항 간 상호 참조 관계 발견 (Tier C)"""
        all_articles = article_service.parse_all_pdfs()
        pattern = re.compile(r"제(\d+)조(?:의(\d+))?(?:제(\d+)항)?(?:에\s*따른|의\s*규정|을\s*준용)")

        new_refs = 0
        # 세션 내 중복 방지 (source_type, source_id, target_type, target_id, relation_type)
        added_keys = set()

        for article in all_articles:
            matches = pattern.findall(article.content)
            for match in matches:
                ref_num = int(match[0])
                ref_article = f"제{ref_num}조"

                if ref_article == article.article_number:
                    continue

                key = ("article", article.article_number, "article", ref_article, "CROSS_REFERENCES")
                if key in added_keys:
                    continue

                # 이미 DB에 존재하는지 확인
                exists = db.query(SemanticMapping).filter(
                    SemanticMapping.source_type == "article",
                    SemanticMapping.source_id == article.article_number,
                    SemanticMapping.target_type == "article",
                    SemanticMapping.target_id == ref_article,
                    SemanticMapping.relation_type == "CROSS_REFERENCES",
                ).first()
                if exists:
                    added_keys.add(key)
                    continue

                sm = SemanticMapping(
                    source_type="article",
                    source_id=article.article_number,
                    target_type="article",
                    target_id=ref_article,
                    relation_type="CROSS_REFERENCES",
                    relation_detail=f"{article.article_number}이 {ref_article}를 참조",
                    confidence=0.9,
                    discovery_method="reference",
                    discovery_tier="C",
                )
                db.add(sm)
                added_keys.add(key)
                new_refs += 1

                # 참조된 조항의 가이드를 참조하는 조항에 전파 (confidence 감쇠)
                ref_guides = (
                    db.query(RegGuideMapping)
                    .filter(RegGuideMapping.article_number == ref_article)
                    .all()
                )
                for rg in ref_guides:
                    guide_key = ("article", article.article_number, "guide", str(rg.guide_id), "SUPPLEMENTS")
                    if guide_key in added_keys:
                        continue

                    exists2 = db.query(SemanticMapping).filter(
                        SemanticMapping.source_type == "article",
                        SemanticMapping.source_id == article.article_number,
                        SemanticMapping.target_type == "guide",
                        SemanticMapping.target_id == str(rg.guide_id),
                        SemanticMapping.relation_type == "SUPPLEMENTS",
                    ).first()
                    if exists2:
                        added_keys.add(guide_key)
                        continue

                    sm2 = SemanticMapping(
                        source_type="article",
                        source_id=article.article_number,
                        target_type="guide",
                        target_id=str(rg.guide_id),
                        relation_type="SUPPLEMENTS",
                        relation_detail=f"참조전파: {ref_article} → {article.article_number}",
                        confidence=0.72,
                        discovery_method="reference",
                        discovery_tier="C",
                    )
                    db.add(sm2)
                    added_keys.add(guide_key)
                    new_refs += 1

        db.commit()
        logger.info(f"상호 참조 발견 완료: {new_refs}건")

        return {"status": "completed", "new_references": new_refs}

    # ===================================================================
    #  조회 메서드
    # ===================================================================

    def get_article_norms(self, db: Session, article_number: str) -> dict:
        """특정 법조항의 규범명제 + 연결 가이드 조회"""
        norms = (
            db.query(NormStatement)
            .filter(NormStatement.article_number == article_number)
            .order_by(NormStatement.statement_order)
            .all()
        )

        # 간소화된 가이드 조회
        sm_list = (
            db.query(SemanticMapping)
            .filter(SemanticMapping.source_id == article_number)
            .filter(SemanticMapping.target_type == "guide")
            .order_by(SemanticMapping.confidence.desc())
            .all()
        )

        guides = []
        for sm in sm_list:
            try:
                guide = db.query(KoshaGuide).filter(KoshaGuide.id == int(sm.target_id)).first()
                if guide:
                    guides.append({
                        "guide_code": guide.guide_code,
                        "title": guide.title,
                        "classification": guide.classification,
                        "relation_type": sm.relation_type,
                        "confidence": sm.confidence,
                        "discovery_method": sm.discovery_method,
                    })
            except (ValueError, Exception):
                continue

        # 법조항 제목 가져오기
        article_info = article_service._find_article_by_number(article_number)
        article_title = article_info["title"] if article_info else None

        return {
            "article_number": article_number,
            "article_title": article_title,
            "total_norms": len(norms),
            "norms": [
                {
                    "id": n.id,
                    "article_number": n.article_number,
                    "paragraph": n.paragraph,
                    "statement_order": n.statement_order,
                    "subject_role": n.subject_role,
                    "action": n.action,
                    "object": n.object,
                    "condition_text": n.condition_text,
                    "legal_effect": n.legal_effect,
                    "effect_description": n.effect_description,
                    "full_text": n.full_text,
                    "norm_category": n.norm_category,
                }
                for n in norms
            ],
            "linked_guides": guides,
        }

    def get_mapping_stats(self, db: Session) -> dict:
        """전체 매핑 통계"""
        # 전체 법조항 수
        all_articles = article_service.parse_all_pdfs()
        total_articles = len(set(a.article_number for a in all_articles))

        # 매핑된 법조항 (explicit)
        explicit_mapped = db.query(distinct(RegGuideMapping.article_number)).count()

        # semantic_mappings에서 추가 매핑
        sm_mapped = db.query(distinct(SemanticMapping.source_id)).filter(
            SemanticMapping.source_type == "article",
            SemanticMapping.target_type == "guide",
        ).count()

        # 전체 매핑된 법조항 (합집합)
        all_mapped_articles = set(
            row[0] for row in db.query(distinct(RegGuideMapping.article_number)).all()
        )
        sm_mapped_articles = set(
            row[0] for row in
            db.query(distinct(SemanticMapping.source_id))
            .filter(SemanticMapping.source_type == "article", SemanticMapping.target_type == "guide")
            .all()
        )
        total_mapped_articles = len(all_mapped_articles | sm_mapped_articles)

        # 가이드 통계
        total_guides = db.query(KoshaGuide).count()
        mapped_guide_ids = set(
            row[0] for row in db.query(distinct(RegGuideMapping.guide_id)).all()
        )
        sm_guide_ids = set(
            row[0] for row in
            db.query(distinct(SemanticMapping.target_id))
            .filter(SemanticMapping.target_type == "guide")
            .all()
        )
        # sm_guide_ids는 문자열이므로 변환
        try:
            sm_guide_ids_int = {int(x) for x in sm_guide_ids if x.isdigit()}
        except Exception:
            sm_guide_ids_int = set()
        total_mapped_guides = len(mapped_guide_ids | sm_guide_ids_int)

        # 매핑 건수
        total_explicit = db.query(RegGuideMapping).count()
        total_semantic = db.query(SemanticMapping).count()

        # 관계 유형별 분포
        relation_counts = dict(
            db.query(SemanticMapping.relation_type, sa_func.count())
            .group_by(SemanticMapping.relation_type)
            .all()
        )

        # 발견 방법별 분포
        discovery_counts = dict(
            db.query(SemanticMapping.discovery_method, sa_func.count())
            .group_by(SemanticMapping.discovery_method)
            .all()
        )

        # 커버리지 개선 비교
        before_article_pct = round(len(all_mapped_articles) / total_articles * 100, 1) if total_articles else 0
        after_article_pct = round(total_mapped_articles / total_articles * 100, 1) if total_articles else 0

        return {
            "total_articles": total_articles,
            "mapped_articles": total_mapped_articles,
            "unmapped_articles": total_articles - total_mapped_articles,
            "total_guides": total_guides,
            "mapped_guides": total_mapped_guides,
            "unmapped_guides": total_guides - total_mapped_guides,
            "total_explicit_mappings": total_explicit,
            "total_semantic_mappings": total_semantic,
            "mapping_by_relation_type": relation_counts,
            "mapping_by_discovery": discovery_counts,
            "coverage_improvement": {
                "before": before_article_pct,
                "after": after_article_pct,
            },
        }

    def get_gap_analysis(self, db: Session) -> dict:
        """미매핑 현황 + 자동 발견 후보"""
        all_articles = article_service.parse_all_pdfs()
        article_map = {a.article_number: a for a in all_articles}

        # 매핑된 법조항
        mapped_articles = set(
            row[0] for row in db.query(distinct(RegGuideMapping.article_number)).all()
        )
        sm_mapped = set(
            row[0] for row in
            db.query(distinct(SemanticMapping.source_id))
            .filter(SemanticMapping.source_type == "article", SemanticMapping.target_type == "guide")
            .all()
        )
        all_mapped = mapped_articles | sm_mapped

        # 미매핑 법조항
        unmapped_articles = []
        for art_num in sorted(set(a.article_number for a in all_articles)):
            if art_num in all_mapped:
                continue

            art = article_map.get(art_num)
            norm_cat = None
            norm = db.query(NormStatement).filter(
                NormStatement.article_number == art_num
            ).first()
            if norm:
                norm_cat = norm.norm_category

            # 자동 발견 후보
            suggestions = (
                db.query(SemanticMapping)
                .filter(SemanticMapping.source_id == art_num, SemanticMapping.target_type == "guide")
                .order_by(SemanticMapping.confidence.desc())
                .limit(3)
                .all()
            )

            suggested_guides = []
            for sg in suggestions:
                try:
                    guide = db.query(KoshaGuide).filter(KoshaGuide.id == int(sg.target_id)).first()
                    if guide:
                        suggested_guides.append({
                            "guide_code": guide.guide_code,
                            "title": guide.title,
                            "classification": guide.classification,
                            "relation_type": sg.relation_type,
                            "confidence": sg.confidence,
                            "discovery_method": sg.discovery_method,
                        })
                except Exception:
                    continue

            unmapped_articles.append({
                "article_number": art_num,
                "article_title": art.title if art else None,
                "norm_category": norm_cat,
                "suggested_guides": suggested_guides,
            })

        # 미매핑 가이드
        mapped_guide_ids = set(
            row[0] for row in db.query(distinct(RegGuideMapping.guide_id)).all()
        )
        sm_guide_ids = set()
        for row in db.query(distinct(SemanticMapping.target_id)).filter(
            SemanticMapping.target_type == "guide"
        ).all():
            try:
                sm_guide_ids.add(int(row[0]))
            except (ValueError, Exception):
                pass
        all_mapped_guides = mapped_guide_ids | sm_guide_ids

        all_guides = db.query(KoshaGuide).all()
        unmapped_guides = []
        for guide in all_guides:
            if guide.id in all_mapped_guides:
                continue
            unmapped_guides.append({
                "guide_code": guide.guide_code,
                "title": guide.title,
                "classification": guide.classification,
                "suggested_articles": [],
            })

        # 안전 관련 미매핑 수
        high_priority = sum(
            1 for a in unmapped_articles
            if a.get("norm_category") == "safety"
        )

        return {
            "unmapped_articles": unmapped_articles,
            "unmapped_guides": unmapped_guides,
            "high_priority_count": high_priority,
        }

    def get_article_graph(self, db: Session, article_number: str) -> dict:
        """특정 법조항 중심 그래프 데이터 (vis.js 호환 nodes/edges)"""
        nodes = []
        edges = []
        node_ids = set()

        # 중심 노드: 법조항
        article_info = article_service._find_article_by_number(article_number)
        art_label = f"{article_number}\n{article_info['title']}" if article_info else article_number
        nodes.append({
            "id": article_number,
            "label": art_label,
            "group": "article",
            "shape": "box",
            "color": "#4FC3F7",
        })
        node_ids.add(article_number)

        # 규범명제 노드
        norms = db.query(NormStatement).filter(
            NormStatement.article_number == article_number
        ).all()
        for norm in norms:
            norm_id = f"norm_{norm.id}"
            label = f"{norm.legal_effect}\n{norm.action or ''}"
            nodes.append({
                "id": norm_id,
                "label": label,
                "group": "norm",
                "shape": "ellipse",
                "color": "#81C784" if norm.legal_effect == "OBLIGATION" else "#EF5350",
            })
            node_ids.add(norm_id)
            edges.append({
                "from": article_number,
                "to": norm_id,
                "label": "hasNorm",
                "dashes": False,
            })

        # 연결된 가이드 + 법조항
        sm_list = db.query(SemanticMapping).filter(
            SemanticMapping.source_id == article_number
        ).all()

        for sm in sm_list:
            target_id = sm.target_id
            if sm.target_type == "guide":
                try:
                    guide = db.query(KoshaGuide).filter(KoshaGuide.id == int(target_id)).first()
                    if guide and guide.guide_code not in node_ids:
                        nodes.append({
                            "id": guide.guide_code,
                            "label": f"{guide.guide_code}\n{guide.title[:20]}",
                            "group": "guide",
                            "shape": "diamond",
                            "color": "#FFB74D",
                        })
                        node_ids.add(guide.guide_code)
                    target_id = guide.guide_code if guide else target_id
                except (ValueError, Exception):
                    pass
            elif sm.target_type == "article" and target_id not in node_ids:
                nodes.append({
                    "id": target_id,
                    "label": target_id,
                    "group": "article",
                    "shape": "box",
                    "color": "#4FC3F7",
                })
                node_ids.add(target_id)

            edges.append({
                "from": article_number,
                "to": target_id,
                "label": sm.relation_type,
                "dashes": sm.discovery_method == "vector",
                "color": {"opacity": sm.confidence},
            })

        return {"nodes": nodes, "edges": edges}

    def get_full_graph(self, db: Session, limit: int = 100) -> dict:
        """전체 온톨로지 그래프 데이터"""
        nodes = []
        edges = []
        node_ids = set()

        # 상위 매핑을 가진 법조항부터 로드
        top_articles = (
            db.query(SemanticMapping.source_id, sa_func.count().label("cnt"))
            .filter(SemanticMapping.source_type == "article")
            .group_by(SemanticMapping.source_id)
            .order_by(sa_func.count().desc())
            .limit(limit)
            .all()
        )

        for art_num, cnt in top_articles:
            if art_num not in node_ids:
                article_info = article_service._find_article_by_number(art_num)
                label = f"{art_num}\n({article_info['title'][:15]})" if article_info else art_num
                nodes.append({
                    "id": art_num,
                    "label": label,
                    "group": "article",
                    "shape": "box",
                    "color": "#4FC3F7",
                    "value": cnt,
                })
                node_ids.add(art_num)

            # 이 법조항의 매핑
            sms = db.query(SemanticMapping).filter(
                SemanticMapping.source_id == art_num
            ).limit(5).all()

            for sm in sms:
                target_label = sm.target_id
                if sm.target_type == "guide":
                    try:
                        guide = db.query(KoshaGuide).filter(KoshaGuide.id == int(sm.target_id)).first()
                        if guide:
                            target_label = guide.guide_code
                            if target_label not in node_ids:
                                nodes.append({
                                    "id": target_label,
                                    "label": f"{guide.guide_code}\n{guide.title[:12]}",
                                    "group": "guide",
                                    "shape": "diamond",
                                    "color": "#FFB74D",
                                })
                                node_ids.add(target_label)
                    except (ValueError, Exception):
                        if sm.target_id not in node_ids:
                            nodes.append({
                                "id": sm.target_id,
                                "label": sm.target_id,
                                "group": "unknown",
                                "shape": "dot",
                            })
                            node_ids.add(sm.target_id)
                        target_label = sm.target_id
                elif sm.target_type == "article" and sm.target_id not in node_ids:
                    nodes.append({
                        "id": sm.target_id,
                        "label": sm.target_id,
                        "group": "article",
                        "shape": "box",
                        "color": "#4FC3F7",
                    })
                    node_ids.add(sm.target_id)
                    target_label = sm.target_id

                edges.append({
                    "from": art_num,
                    "to": target_label,
                    "label": sm.relation_type,
                    "dashes": sm.discovery_method == "vector",
                })

        return {"nodes": nodes, "edges": edges}

    def get_semantic_mappings(
        self,
        db: Session,
        relation_type: Optional[str] = None,
        discovery_method: Optional[str] = None,
        min_confidence: float = 0.0,
        limit: int = 50,
        offset: int = 0,
    ) -> list:
        """의미적 매핑 목록 조회 (필터링)"""
        query = db.query(SemanticMapping)

        if relation_type:
            query = query.filter(SemanticMapping.relation_type == relation_type)
        if discovery_method:
            query = query.filter(SemanticMapping.discovery_method == discovery_method)
        if min_confidence > 0:
            query = query.filter(SemanticMapping.confidence >= min_confidence)

        query = query.order_by(SemanticMapping.confidence.desc())
        results = query.offset(offset).limit(limit).all()

        mappings = []
        for sm in results:
            # 레이블 조회
            source_label = sm.source_id
            target_label = sm.target_id

            if sm.target_type == "guide":
                try:
                    guide = db.query(KoshaGuide).filter(KoshaGuide.id == int(sm.target_id)).first()
                    if guide:
                        target_label = f"{guide.guide_code} - {guide.title}"
                except (ValueError, Exception):
                    pass

            mappings.append({
                "id": sm.id,
                "source_type": sm.source_type,
                "source_id": sm.source_id,
                "source_label": source_label,
                "target_type": sm.target_type,
                "target_id": sm.target_id,
                "target_label": target_label,
                "relation_type": sm.relation_type,
                "relation_detail": sm.relation_detail,
                "confidence": sm.confidence,
                "discovery_method": sm.discovery_method,
                "discovery_tier": sm.discovery_tier,
            })

        return mappings

    # ===================================================================
    #  분석 연동 메서드
    # ===================================================================

    # 카테고리별 법조항 범위 (산업안전보건규칙 장 구조)
    CATEGORY_ARTICLE_RANGE = {
        "physical": [(32, 67), (86, 166)],
        "chemical": [(225, 290)],
        "electrical": [(301, 339)],
        "ergonomic": [(656, 671)],
        "environmental": [(559, 586)],
        "biological": [(592, 604)],
    }

    def find_related_articles_for_hazards(
        self, db: Session, hazard_descriptions: List[str], hazard_categories: List[str]
    ) -> List[dict]:
        """위험요소 설명+카테고리로 관련 법조항 + 규범명제 + 가이드 찾기

        우선순위: 벡터 검색(의미적 유사도) > 카테고리 범위(보충)
        """
        # 벡터 검색 결과를 우선 수집 (순서 유지용 리스트)
        vector_articles = []
        category_articles = set()

        # 1) 벡터 검색: hazard descriptions으로 의미적으로 가장 관련된 법조항 (최우선)
        if article_service.collection.count() > 0:
            try:
                from openai import OpenAI
                openai_sync = OpenAI(api_key=article_service._openai.api_key)

                combined_desc = " ".join(hazard_descriptions)[:500]
                response = openai_sync.embeddings.create(
                    model="text-embedding-3-small",
                    input=[combined_desc],
                )
                query_embedding = response.data[0].embedding

                chroma_results = article_service.collection.query(
                    query_embeddings=[query_embedding],
                    n_results=10,
                    include=["metadatas", "distances"],
                )

                if chroma_results and chroma_results["metadatas"] and chroma_results["metadatas"][0]:
                    for i, meta in enumerate(chroma_results["metadatas"][0]):
                        distance = chroma_results["distances"][0][i]
                        if (1 - distance) >= 0.55:
                            art_num = meta.get("article_number", "")
                            if art_num and art_num not in vector_articles:
                                vector_articles.append(art_num)
            except Exception as e:
                logger.warning(f"벡터 검색 실패: {e}")

        # 2) 카테고리 기반: 보충용 (벡터 결과가 부족할 때만)
        cat_ranges = []
        for cat in set(hazard_categories):
            cat_ranges.extend(self.CATEGORY_ARTICLE_RANGE.get(cat, []))

        if cat_ranges:
            all_norm_articles = set(
                row[0] for row in
                db.query(NormStatement.article_number).distinct().all()
            )
            for art_num_str in all_norm_articles:
                art_num = self._extract_article_num(art_num_str)
                if art_num:
                    for r_start, r_end in cat_ranges:
                        if r_start <= art_num <= r_end:
                            category_articles.add(art_num_str)
                            break

        # 벡터 검색 결과 우선, 카테고리 결과 보충 (최대 10개)
        ordered_articles = list(vector_articles)
        for art in sorted(category_articles):
            if art not in ordered_articles:
                ordered_articles.append(art)

        # 3) 각 법조항의 규범명제 + 연결 가이드 조회 (최대 10개)
        result = []
        for article_number in ordered_articles[:10]:
            norms = (
                db.query(NormStatement)
                .filter(NormStatement.article_number == article_number)
                .order_by(NormStatement.statement_order)
                .limit(5)
                .all()
            )
            if not norms:
                continue

            sm_list = (
                db.query(SemanticMapping)
                .filter(
                    SemanticMapping.source_id == article_number,
                    SemanticMapping.target_type == "guide",
                )
                .order_by(SemanticMapping.confidence.desc())
                .limit(5)
                .all()
            )

            guides = []
            for sm in sm_list:
                try:
                    guide = db.query(KoshaGuide).filter(KoshaGuide.id == int(sm.target_id)).first()
                    if guide:
                        guides.append({
                            "guide_code": guide.guide_code,
                            "title": guide.title,
                            "relation_type": sm.relation_type,
                            "confidence": sm.confidence,
                        })
                except (ValueError, Exception):
                    continue

            article_info = article_service._find_article_by_number(article_number)
            result.append({
                "article_number": article_number,
                "article_title": article_info["title"] if article_info else None,
                "norms": [
                    {
                        "article_number": n.article_number,
                        "legal_effect": n.legal_effect,
                        "action": n.action,
                        "full_text": n.full_text,
                    }
                    for n in norms
                ],
                "linked_guides": guides,
            })

        return result

    def get_semantic_boost_for_guides(
        self, db: Session, guide_codes: List[str]
    ) -> Dict[str, float]:
        """가이드 코드별 시맨틱 매핑 부스트 점수"""
        BOOST_MAP = {
            "SPECIFIES_CRITERIA": 0.25,
            "IMPLEMENTS": 0.20,
            "SPECIFIES_METHOD": 0.15,
            "CROSS_REFERENCES": 0.10,
            "SUPPLEMENTS": 0.05,
        }

        if not guide_codes:
            return {}

        guides = db.query(KoshaGuide).filter(KoshaGuide.guide_code.in_(guide_codes)).all()
        code_to_id = {g.guide_code: str(g.id) for g in guides}

        boost_result = {}
        for code, gid in code_to_id.items():
            best_sm = (
                db.query(SemanticMapping)
                .filter(
                    SemanticMapping.target_id == gid,
                    SemanticMapping.target_type == "guide",
                )
                .order_by(SemanticMapping.confidence.desc())
                .first()
            )
            if best_sm:
                boost_result[code] = BOOST_MAP.get(best_sm.relation_type, 0.0)

        return boost_result


ontology_service = OntologyService()
