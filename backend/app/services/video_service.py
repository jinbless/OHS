import json
import re
import logging
from pathlib import Path
from typing import List, Optional
from sqlalchemy.orm import Session

from app.db.models import SafetyVideo
from app.models.resource import Resource, ResourceType

logger = logging.getLogger(__name__)


class VideoService:
    """KOSHA 안전 숏폼영상 서비스 - 3-Layer 매칭"""

    def _extract_video_id(self, url: str) -> Optional[str]:
        """YouTube URL에서 video ID 추출"""
        match = re.search(r'shorts/([a-zA-Z0-9_-]+)', url)
        return match.group(1) if match else None

    def _to_resource(self, video: SafetyVideo, score: float = 0.5) -> Resource:
        """SafetyVideo → Resource 변환"""
        video_id = self._extract_video_id(video.url)
        thumbnail = f"https://img.youtube.com/vi/{video_id}/0.jpg" if video_id else None
        cats = json.loads(video.hazard_categories) if video.hazard_categories else []
        return Resource(
            id=f"video-{video.id}",
            type=ResourceType.VIDEO,
            title=video.title,
            description=video.category,
            url=video.url,
            source="KOSHA 숏폼",
            hazard_categories=cats,
            thumbnail_url=thumbnail,
        )

    # ── 시드 데이터 로드 ──────────────────────────────────

    def seed_videos(self, db: Session, force: bool = False) -> int:
        """safety_videos.json에서 DB로 시드 데이터 로드"""
        existing = db.query(SafetyVideo).count()
        if existing > 0 and not force:
            logger.info(f"SafetyVideo 이미 {existing}개 존재, 스킵")
            return existing

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
            # URL unique 제약 충돌 시 개별 insert 시도
            count = 0
            for v in videos:
                existing = db.query(SafetyVideo).filter_by(url=v["url"]).first()
                if existing:
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

    # ── Layer 1: 카테고리 매칭 ─────────────────────────────

    def match_by_category(self, db: Session, categories: List[str], limit: int = 10) -> List[dict]:
        """hazard_categories 기반 매칭"""
        if not categories:
            return []

        all_videos = db.query(SafetyVideo).all()
        results = []
        for video in all_videos:
            cats = json.loads(video.hazard_categories) if video.hazard_categories else []
            overlap = set(categories) & set(cats)
            if overlap:
                score = len(overlap) / max(len(categories), 1)
                results.append({"video": video, "score": score, "method": "category"})

        results.sort(key=lambda x: x["score"], reverse=True)
        return results[:limit]

    # ── Layer 2: 키워드 매칭 ──────────────────────────────

    def match_by_keywords(self, db: Session, hazard_descriptions: List[str], limit: int = 10) -> List[dict]:
        """위험요소 설명에서 키워드 추출 후 영상 제목+태그 매칭"""
        if not hazard_descriptions:
            return []

        # 위험요소 설명에서 2글자 이상 키워드 추출
        keywords = set()
        for desc in hazard_descriptions:
            words = re.findall(r'[가-힣]{2,}', desc)
            keywords.update(words)

        # 불용어 제거
        stopwords = {"작업", "위험", "필요", "있는", "하는", "되는", "경우", "가능", "발생", "해야", "때문",
                     "이상", "하여", "통해", "대한", "관련", "따른", "인한", "것이", "등의", "수가"}
        keywords -= stopwords
        if not keywords:
            return []

        all_videos = db.query(SafetyVideo).filter(SafetyVideo.is_korean == 1).all()
        results = []
        for video in all_videos:
            tags = json.loads(video.tags) if video.tags else []
            search_text = video.title + " " + " ".join(tags) + " " + video.category
            hits = sum(1 for kw in keywords if kw in search_text)
            if hits > 0:
                score = min(1.0, hits * 0.2)
                results.append({"video": video, "score": score, "method": "keyword"})

        results.sort(key=lambda x: x["score"], reverse=True)
        return results[:limit]

    # ── Layer 3: 온톨로지 경유 매칭 ───────────────────────

    def match_by_ontology(
        self, db: Session, norm_articles: List[str], guide_classifications: List[str], limit: int = 10
    ) -> List[dict]:
        """법조항 → 가이드 분류 → 영상 분야 매칭

        norm_articles: 매칭된 법조항 번호 리스트 (예: ["제42조", "제80조"])
        guide_classifications: 관련 가이드 분류코드 리스트 (예: ["G", "C", "M"])
        """
        if not guide_classifications and not norm_articles:
            return []

        # 가이드 분류 → 영상 분야 키워드 매핑
        classification_keywords = {
            "G": ["일반", "안전", "보호구", "정리정돈"],
            "C": ["건설", "비계", "사다리", "추락", "개구부", "지붕", "철골", "거푸집", "크레인"],
            "M": ["기계", "프레스", "롤러", "컨베이어", "로봇", "절단", "끼임"],
            "E": ["전기", "감전", "정전", "활선"],
            "H": ["화학", "폭발", "중독", "밀폐", "질식", "유해물질"],
            "B": ["보건", "건강", "근골격계", "분진", "온열"],
        }

        match_keywords = set()
        for cls in guide_classifications:
            kws = classification_keywords.get(cls, [])
            match_keywords.update(kws)

        # 법조항 번호에서 키워드 유추
        for article in norm_articles:
            num_match = re.search(r'(\d+)', article)
            if num_match:
                num = int(num_match.group(1))
                if 32 <= num <= 67 or 86 <= num <= 166:
                    match_keywords.update(["추락", "건설", "비계", "사다리", "끼임"])
                elif 225 <= num <= 290:
                    match_keywords.update(["화학", "폭발", "중독"])
                elif 301 <= num <= 339:
                    match_keywords.update(["전기", "감전"])

        if not match_keywords:
            return []

        all_videos = db.query(SafetyVideo).all()
        results = []
        for video in all_videos:
            search_text = video.title + " " + video.category
            hits = sum(1 for kw in match_keywords if kw in search_text)
            if hits > 0:
                score = min(0.9, hits * 0.15)
                results.append({"video": video, "score": score, "method": "ontology"})

        results.sort(key=lambda x: x["score"], reverse=True)
        return results[:limit]

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
        """3-Layer 매칭 통합: 카테고리 + 키워드 + 온톨로지"""

        video_scores: dict[int, dict] = {}  # video.id → {video, score, methods}

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

        # Layer 1: 카테고리 (가중치 0.4)
        cat_matches = self.match_by_category(db, hazard_categories, limit=15)
        _merge(cat_matches, weight=0.4)

        # Layer 2: 키워드 (가중치 0.4)
        kw_matches = self.match_by_keywords(db, hazard_descriptions, limit=15)
        _merge(kw_matches, weight=0.4)

        # Layer 3: 온톨로지 (가중치 0.3)
        if norm_articles or guide_classifications:
            onto_matches = self.match_by_ontology(
                db,
                norm_articles or [],
                guide_classifications or [],
                limit=15,
            )
            _merge(onto_matches, weight=0.3)

        # 한국어 영상 우선 부스트
        for vid, entry in video_scores.items():
            if entry["video"].is_korean:
                entry["score"] += 0.05
            # 다중 레이어 매칭 보너스
            if len(set(entry["methods"])) >= 2:
                entry["score"] += 0.1
            if len(set(entry["methods"])) >= 3:
                entry["score"] += 0.15

        # 정렬 및 상위 N개 반환
        sorted_entries = sorted(video_scores.values(), key=lambda x: x["score"], reverse=True)

        results = []
        for entry in sorted_entries[:max_results]:
            results.append(self._to_resource(entry["video"], entry["score"]))

        return results


video_service = VideoService()
