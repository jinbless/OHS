import json
import re
import logging
from pathlib import Path
from typing import List, Optional
from sqlalchemy.orm import Session

from app.db.models import SafetyVideo
from app.models.resource import Resource, ResourceType
from app.utils.taxonomy import code_to_major

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

    # ── hazard_code 직접 매칭 ─────────────────────────────

    def find_related_videos(
        self,
        db: Session,
        hazard_codes: List[str],
        hazard_descriptions: Optional[List[str]] = None,
        max_results: int = 5,
    ) -> List[Resource]:
        """hazard_code 직접 매칭: 서브카테고리 일치하는 영상만 반환.
        일치하는 영상이 없으면 빈 리스트 (폴백 없음).
        대분류별 다양성 보장: 각 대분류에서 최소 1개 영상."""

        if not hazard_codes:
            return []

        # 입력 코드 정규화 및 대분류 그룹화
        query_codes = {c.upper() for c in hazard_codes}
        query_majors = {}  # major → set of codes
        for c in query_codes:
            m = code_to_major(c)
            if m:
                query_majors.setdefault(m, set()).add(c)

        all_videos = db.query(SafetyVideo).all()

        # 대분류별 후보 수집
        major_candidates: dict[str, list[dict]] = {m: [] for m in query_majors}
        all_scored: list[dict] = []

        for video in all_videos:
            video_codes_raw = json.loads(video.hazard_codes) if video.hazard_codes else []
            if not video_codes_raw:
                continue
            video_codes = {c.upper() for c in video_codes_raw}

            overlap = query_codes & video_codes
            if not overlap:
                continue

            # 점수: 일치 코드 수 / 쿼리 코드 수
            precision = len(overlap) / len(query_codes)
            kw_bonus = 0.0
            if hazard_descriptions:
                kw_bonus = self._keyword_score(video, hazard_descriptions) * 0.2
            score = precision + kw_bonus

            entry = {"video": video, "score": score, "overlap": overlap}
            all_scored.append(entry)

            # 각 대분류 후보에 추가
            for m, m_codes in query_majors.items():
                if overlap & m_codes:
                    major_candidates[m].append(entry)

        if not all_scored:
            return []

        # 대분류별 다양성 보장: 각 대분류에서 최고점 1개씩 선점
        selected_ids: set[int] = set()
        final: list[dict] = []

        for m in sorted(major_candidates.keys()):
            cands = major_candidates[m]
            if not cands:
                continue
            cands.sort(key=lambda x: x["score"], reverse=True)
            for c in cands:
                vid = c["video"].id
                if vid not in selected_ids:
                    selected_ids.add(vid)
                    final.append(c)
                    break

        # 나머지 슬롯은 전체 점수 순으로 채우기
        all_scored.sort(key=lambda x: x["score"], reverse=True)
        for entry in all_scored:
            if len(final) >= max_results:
                break
            vid = entry["video"].id
            if vid not in selected_ids:
                selected_ids.add(vid)
                final.append(entry)

        # 최종 정렬 (점수순)
        final.sort(key=lambda x: x["score"], reverse=True)

        # 최소 점수 컷오프: 최고 점수의 40% 미만은 제외 (관련성 낮은 영상 필터)
        if final:
            top_score = final[0]["score"]
            cutoff = top_score * 0.4
            final = [e for e in final if e["score"] >= cutoff]

        return [self._to_resource(e["video"], e["score"]) for e in final[:max_results]]

    def _keyword_score(self, video: SafetyVideo, descriptions: List[str]) -> float:
        """영상 제목+태그+description과 위험 설명 간 키워드 매칭 점수"""
        keywords = set()
        for desc in descriptions:
            words = re.findall(r'[가-힣]{2,}', desc)
            keywords.update(words)

        stopwords = {"작업", "위험", "필요", "있는", "하는", "되는", "경우", "가능", "발생", "해야", "때문",
                     "이상", "하여", "통해", "대한", "관련", "따른", "인한", "것이", "등의", "수가",
                     "안전", "보건", "교육", "예방", "사고", "산업", "근로자", "사업장"}
        keywords -= stopwords
        if not keywords:
            return 0.0

        tags = json.loads(video.tags) if video.tags else []
        desc = video.description or ""
        search_text = video.title + " " + " ".join(tags) + " " + video.category + " " + desc
        hits = sum(1 for kw in keywords if kw in search_text)
        return min(1.0, hits * 0.15)


video_service = VideoService()
