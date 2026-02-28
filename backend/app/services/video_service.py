import json
import re
import logging
from pathlib import Path
from typing import List, Optional
from sqlalchemy.orm import Session

from app.db.models import SafetyVideo
from app.models.resource import Resource, ResourceType
from app.utils.taxonomy import get_chapter_for_article, code_to_major

logger = logging.getLogger(__name__)


class VideoService:
    """KOSHA 안전 숏폼영상 서비스 - hazard_codes 기반 정밀 매칭"""

    def _extract_video_id(self, url: str) -> Optional[str]:
        """YouTube URL에서 video ID 추출"""
        match = re.search(r'shorts/([a-zA-Z0-9_-]+)', url)
        return match.group(1) if match else None

    def _to_resource(self, video: SafetyVideo, score: float = 0.5) -> Resource:
        """SafetyVideo → Resource 변환"""
        video_id = self._extract_video_id(video.url)
        thumbnail = f"https://img.youtube.com/vi/{video_id}/0.jpg" if video_id else None
        codes = json.loads(video.hazard_codes) if video.hazard_codes else []
        return Resource(
            id=f"video-{video.id}",
            type=ResourceType.VIDEO,
            title=video.title,
            description=video.description or video.category,
            url=video.url,
            source="KOSHA 숏폼",
            hazard_categories=codes,
            thumbnail_url=thumbnail,
        )

    # ── 시드 데이터 로드 ──────────────────────────────────

    def seed_videos(self, db: Session, force: bool = False) -> int:
        """safety_videos.json에서 DB로 시드 데이터 로드"""
        existing = db.query(SafetyVideo).count()
        if existing > 0 and not force:
            logger.info(f"SafetyVideo 이미 {existing}개 존재, 스킵")
            return existing

        # force=True일 때 기존 데이터 삭제
        if force and existing > 0:
            db.query(SafetyVideo).delete()
            db.commit()
            logger.info(f"SafetyVideo {existing}개 삭제 후 재로드")

        data_path = Path(__file__).parent.parent / "data" / "safety_videos.json"
        if not data_path.exists():
            logger.warning("safety_videos.json 파일 없음")
            return 0

        with open(data_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        videos = data.get("videos", [])
        count = 0
        for v in videos:
            video_id = self._extract_video_id(v["url"])
            thumbnail = f"https://img.youtube.com/vi/{video_id}/0.jpg" if video_id else None
            sv = SafetyVideo(
                title=v["title"],
                url=v["url"],
                category=v["category"],
                tags=json.dumps(v.get("tags", []), ensure_ascii=False),
                hazard_categories=json.dumps(v.get("hazard_categories", []), ensure_ascii=False),
                hazard_codes=json.dumps(v.get("hazard_codes", []), ensure_ascii=False),
                description=v.get("description", ""),
                series=v.get("series"),
                is_korean=1 if v.get("is_korean", True) else 0,
                thumbnail_url=thumbnail,
            )
            db.add(sv)
            count += 1

        try:
            db.commit()
        except Exception:
            db.rollback()
            count = 0
            for v in videos:
                existing_v = db.query(SafetyVideo).filter_by(url=v["url"]).first()
                if existing_v:
                    count += 1
                    continue
                video_id = self._extract_video_id(v["url"])
                thumbnail = f"https://img.youtube.com/vi/{video_id}/0.jpg" if video_id else None
                sv = SafetyVideo(
                    title=v["title"],
                    url=v["url"],
                    category=v["category"],
                    tags=json.dumps(v.get("tags", []), ensure_ascii=False),
                    hazard_categories=json.dumps(v.get("hazard_categories", []), ensure_ascii=False),
                    hazard_codes=json.dumps(v.get("hazard_codes", []), ensure_ascii=False),
                    description=v.get("description", ""),
                    series=v.get("series"),
                    is_korean=1 if v.get("is_korean", True) else 0,
                    thumbnail_url=thumbnail,
                )
                db.add(sv)
                try:
                    db.commit()
                    count += 1
                except Exception:
                    db.rollback()
                    count += 1
        logger.info(f"SafetyVideo {count}개 시드 완료")
        return count

    # ── Layer 1: hazard_codes 정밀 매칭 ─────────────────────

    def match_by_category_weights(
        self, db: Session, category_weights: dict[str, float], limit: int = 10
    ) -> List[dict]:
        """대분류 가중치 기반 매칭 — 영상의 대분류가 입력 카테고리와 겹칠수록 높은 점수"""
        if not category_weights:
            return []

        all_videos = db.query(SafetyVideo).all()
        results = []
        for video in all_videos:
            codes = json.loads(video.hazard_codes) if video.hazard_codes else []
            if not codes:
                continue

            # 영상의 대분류 집합
            video_majors = set()
            for c in codes:
                m = code_to_major(c.upper())
                if m:
                    video_majors.add(m)

            # 영상이 매칭하는 카테고리 가중치 합산
            score = sum(category_weights.get(m, 0) for m in video_majors)
            if score > 0:
                results.append({"video": video, "score": score, "method": "hazard_code"})

        results.sort(key=lambda x: x["score"], reverse=True)
        return results[:limit]

    # ── Layer 2: 키워드 매칭 (제목 + 태그 + description) ────

    def match_by_keywords(self, db: Session, hazard_descriptions: List[str], limit: int = 10) -> List[dict]:
        """위험요소 설명에서 키워드 추출 후 영상 제목+태그+description 매칭"""
        if not hazard_descriptions:
            return []

        keywords = set()
        for desc in hazard_descriptions:
            words = re.findall(r'[가-힣]{2,}', desc)
            keywords.update(words)

        stopwords = {"작업", "위험", "필요", "있는", "하는", "되는", "경우", "가능", "발생", "해야", "때문",
                     "이상", "하여", "통해", "대한", "관련", "따른", "인한", "것이", "등의", "수가",
                     "안전", "보건", "교육", "예방", "사고", "산업", "근로자", "사업장"}
        keywords -= stopwords
        if not keywords:
            return []

        all_videos = db.query(SafetyVideo).filter(SafetyVideo.is_korean == 1).all()
        results = []
        for video in all_videos:
            tags = json.loads(video.tags) if video.tags else []
            desc = video.description or ""
            search_text = video.title + " " + " ".join(tags) + " " + video.category + " " + desc
            hits = sum(1 for kw in keywords if kw in search_text)
            if hits > 0:
                score = min(1.0, hits * 0.15)
                results.append({"video": video, "score": score, "method": "keyword"})

        results.sort(key=lambda x: x["score"], reverse=True)
        return results[:limit]

    # ── Layer 3: 온톨로지 경유 매칭 ───────────────────────

    def match_by_ontology(
        self, db: Session, norm_articles: List[str], guide_classifications: List[str], limit: int = 10
    ) -> List[dict]:
        """법조항 → taxonomy → 대분류 가중치 매칭"""
        if not guide_classifications and not norm_articles:
            return []

        # 법조항에서 대분류 유추
        inferred_majors: list[str] = []
        for article in norm_articles:
            num_match = re.search(r'(\d+)', article)
            if num_match:
                num = int(num_match.group(1))
                ch = get_chapter_for_article(num)
                if ch and ch.get("hazard_major"):
                    inferred_majors.append(ch["hazard_major"])

        # KOSHA 분류 → 대분류 매핑
        _CLS_TO_MAJOR = {
            "G": [],
            "C": ["physical"],
            "M": ["physical"],
            "E": ["electrical"],
            "H": ["chemical", "environmental"],
            "B": ["ergonomic", "environmental"],
        }
        for cls in guide_classifications:
            majors = _CLS_TO_MAJOR.get(cls, [])
            inferred_majors.extend(majors)

        if not inferred_majors:
            return []

        # 빈도 기반 가중치
        from collections import Counter
        freq = Counter(inferred_majors)
        total = max(len(inferred_majors), 1)
        weights = {m: c / total for m, c in freq.items()}

        return self.match_by_category_weights(db, weights, limit=limit)

    # ── 통합 매칭 (3-Layer 병합) ──────────────────────────

    def find_related_videos(
        self,
        db: Session,
        hazard_descriptions: List[str],
        hazard_categories: List[str],
        norm_articles: Optional[List[str]] = None,
        guide_classifications: Optional[List[str]] = None,
        max_results: int = 5,
    ) -> List[Resource]:
        """3-Layer 매칭 통합: hazard_codes + 키워드 + 온톨로지"""

        video_scores: dict[int, dict] = {}

        def _merge(matches: List[dict], weight: float):
            for m in matches:
                vid = m["video"].id
                if vid not in video_scores:
                    video_scores[vid] = {
                        "video": m["video"],
                        "score": 0.0,
                        "methods": [],
                    }
                video_scores[vid]["score"] += m["score"] * weight
                video_scores[vid]["methods"].append(m["method"])

        # hazard_categories → 대분류별 가중치 계산
        from collections import Counter
        cat_freq = Counter(hazard_categories)
        total = max(len(hazard_categories), 1)
        category_weights = {cat: count / total for cat, count in cat_freq.items()}

        # Layer 1: 카테고리 가중치 매칭 (weight 0.5)
        if category_weights:
            cat_matches = self.match_by_category_weights(db, category_weights, limit=15)
            _merge(cat_matches, weight=0.5)

        # Layer 2: 키워드 (가중치 0.3)
        kw_matches = self.match_by_keywords(db, hazard_descriptions, limit=15)
        _merge(kw_matches, weight=0.3)

        # Layer 3: 온톨로지 (가중치 0.2)
        if norm_articles or guide_classifications:
            onto_matches = self.match_by_ontology(
                db,
                norm_articles or [],
                guide_classifications or [],
                limit=15,
            )
            _merge(onto_matches, weight=0.2)

        # 한국어 영상 우선 부스트
        for vid, entry in video_scores.items():
            if entry["video"].is_korean:
                entry["score"] += 0.05
            # 다중 레이어 매칭 보너스
            unique_methods = set(entry["methods"])
            if len(unique_methods) >= 2:
                entry["score"] += 0.1
            if len(unique_methods) >= 3:
                entry["score"] += 0.15

        # 정렬 및 상위 N개 반환
        sorted_entries = sorted(video_scores.values(), key=lambda x: x["score"], reverse=True)

        results = []
        for entry in sorted_entries[:max_results]:
            results.append(self._to_resource(entry["video"], entry["score"]))

        return results


video_service = VideoService()
