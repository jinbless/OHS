#!/usr/bin/env python3
"""
law.go.kr에서 산업안전보건기준에 관한 규칙 전체 조문을 크롤링하여
articles_cache.json 형태로 저장하는 스크립트.

Usage:
    python3 crawl_law_articles.py
"""

import json
import re
import sys
from pathlib import Path
from playwright.sync_api import sync_playwright

# 산업안전보건기준에 관한 규칙 lsiSeq
LSI_SEQ = "280187"
URL = f"https://www.law.go.kr/LSW/lsInfoP.do?lsiSeq={LSI_SEQ}&ancYnChk=0#0000"

OUTPUT_DIR = Path(__file__).parent.parent / "data"
OUTPUT_FILE = OUTPUT_DIR / "articles_cache_lawgokr.json"
FINAL_FILE = OUTPUT_DIR / "articles_cache.json"
BACKUP_FILE = OUTPUT_DIR / "articles_cache_pdf_backup.json"


def parse_article_number_and_title(text: str):
    """
    '제3조(전도의 방지) ① 사업주는...' 에서
    article_number='제3조', title='전도의 방지' 추출
    """
    m = re.match(r"(제\d+조(?:의\d+)?)\s*\(([^)]+)\)", text.strip())
    if m:
        return m.group(1), m.group(2)
    # 제목 없이 번호만 있는 경우
    m2 = re.match(r"(제\d+조(?:의\d+)?)", text.strip())
    if m2:
        return m2.group(1), ""
    return None, None


def extract_chapter_info(text: str):
    """편/장/절 헤더에서 메타데이터 추출"""
    # 편: '제2편 안전기준'
    m = re.match(r"제(\d+)편\s+(.+)", text.strip())
    if m:
        return {"type": "part", "number": int(m.group(1)), "name": m.group(2).strip()}
    # 장: '제1장 총칙'
    m = re.match(r"제(\d+)장\s+(.+)", text.strip())
    if m:
        return {"type": "chapter", "number": int(m.group(1)), "name": m.group(2).strip()}
    # 절: '제1절 ...'
    m = re.match(r"제(\d+)절\s+(.+)", text.strip())
    if m:
        return {"type": "section", "number": int(m.group(1)), "name": m.group(2).strip()}
    return None


def crawl_articles():
    """law.go.kr에서 전체 조문 크롤링"""
    print(f"Crawling: {URL}")

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        page.goto(URL, wait_until="networkidle", timeout=60000)
        page.wait_for_timeout(5000)

        title = page.title()
        print(f"Page loaded: {title}")

        # 모든 .lawcon div에서 조문 추출
        raw_articles = page.evaluate("""() => {
            const lawcons = document.querySelectorAll('div.lawcon');
            const results = [];
            for (const lc of lawcons) {
                const text = lc.innerText.trim();
                if (text) {
                    results.push(text);
                }
            }
            return results;
        }""")

        # 편/장/절 헤더도 추출 (lawcon 바깥의 구조 요소)
        headers = page.evaluate("""() => {
            const all = document.querySelectorAll('.pgroup');
            const headers = [];
            for (const pg of all) {
                const text = pg.innerText.trim();
                if (/^제\\d+편/.test(text) || /^제\\d+장/.test(text) || /^제\\d+절/.test(text)) {
                    // This pgroup is a chapter/section header
                    headers.push(text.split('\\n')[0].trim());
                }
            }
            return headers;
        }""")

        browser.close()

    print(f"Raw lawcon elements: {len(raw_articles)}")
    print(f"Chapter headers found: {len(headers)}")

    # 편/장/절 순서 추적을 위한 헤더 인덱스 구축
    all_headers = []
    for h in headers:
        info = extract_chapter_info(h)
        if info:
            all_headers.append(info)

    # 조문 파싱
    articles = []
    current_part = ""
    current_chapter = ""
    current_section = ""
    seen_numbers = set()
    skipped = 0

    for raw_text in raw_articles:
        # 첫 줄에서 조문번호와 제목 추출
        first_line = raw_text.split("\n")[0].strip()

        # 편/장/절 헤더인지 확인
        ch_info = extract_chapter_info(first_line)
        if ch_info:
            if ch_info["type"] == "part":
                current_part = f"제{ch_info['number']}편 {ch_info['name']}"
                current_chapter = ""
                current_section = ""
            elif ch_info["type"] == "chapter":
                current_chapter = f"제{ch_info['number']}장 {ch_info['name']}"
                current_section = ""
            elif ch_info["type"] == "section":
                current_section = f"제{ch_info['number']}절 {ch_info['name']}"
            continue

        # 조문 번호 추출
        art_num, art_title = parse_article_number_and_title(first_line)
        if not art_num:
            # 부칙 등 비조문 요소 스킵
            if "부칙" in first_line or "별표" in first_line:
                skipped += 1
                continue
            # 편/장/절 텍스트가 lawcon에 섞인 경우
            ch = extract_chapter_info(raw_text.strip())
            if ch:
                if ch["type"] == "part":
                    current_part = f"제{ch['number']}편 {ch['name']}"
                    current_chapter = ""
                    current_section = ""
                elif ch["type"] == "chapter":
                    current_chapter = f"제{ch['number']}장 {ch['name']}"
                    current_section = ""
                elif ch["type"] == "section":
                    current_section = f"제{ch['number']}절 {ch['name']}"
                continue
            skipped += 1
            continue

        # 중복 체크 (같은 조문번호 재등장 = 부칙 등)
        if art_num in seen_numbers:
            skipped += 1
            continue
        seen_numbers.add(art_num)

        # content: 조문 전문 (제목 포함)
        content = raw_text.strip()

        # 항 분리
        paragraphs = []
        para_pattern = re.compile(r"([①②③④⑤⑥⑦⑧⑨⑩⑪⑫⑬⑭⑮])\s*")
        parts = para_pattern.split(content)

        if len(parts) > 1:
            # 첫 부분 (항 번호 없는 부분 = 조문 제목줄)
            for i in range(1, len(parts), 2):
                if i + 1 < len(parts):
                    para_num = parts[i]
                    para_text = parts[i + 1].strip()
                    paragraphs.append({
                        "number": para_num,
                        "content": para_text,
                    })
        else:
            # 단일항 조문
            # 조문번호(제목) 이후의 텍스트가 본문
            m = re.match(r"제\d+조(?:의\d+)?\s*\([^)]*\)\s*", content)
            if m:
                body = content[m.end():].strip()
                if body:
                    paragraphs.append({"number": "", "content": body})

        article = {
            "article_number": art_num,
            "title": art_title,
            "content": content,
            "part": current_part,
            "chapter": current_chapter,
            "section": current_section,
            "paragraphs": paragraphs,
            "source": "law.go.kr",
        }
        articles.append(article)

    print(f"\nParsed articles: {len(articles)}")
    print(f"Skipped elements: {skipped}")

    # 숫자 정렬
    def sort_key(a):
        m = re.match(r"제(\d+)조", a["article_number"])
        num = int(m.group(1)) if m else 999
        sub = re.search(r"의(\d+)", a["article_number"])
        sub_num = int(sub.group(1)) if sub else 0
        return (num, sub_num)

    articles.sort(key=sort_key)

    return articles


def save_articles(articles):
    """저장"""
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    # 새 데이터 저장
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(articles, f, ensure_ascii=False, indent=2)
    print(f"\nSaved to: {OUTPUT_FILE}")

    # 기존 데이터 백업
    if FINAL_FILE.exists():
        import shutil
        shutil.copy2(FINAL_FILE, BACKUP_FILE)
        print(f"Backed up old data to: {BACKUP_FILE}")

    # 기존 형식 호환 articles_cache.json도 생성
    # (article_number, title, content, source_file 형식)
    compat_articles = []
    for a in articles:
        compat_articles.append({
            "article_number": a["article_number"],
            "title": a["title"],
            "content": a["content"],
            "source_file": f"law.go.kr (lsiSeq={LSI_SEQ})",
            # 확장 필드
            "part": a.get("part", ""),
            "chapter": a.get("chapter", ""),
            "section": a.get("section", ""),
            "paragraphs": a.get("paragraphs", []),
        })

    with open(FINAL_FILE, "w", encoding="utf-8") as f:
        json.dump(compat_articles, f, ensure_ascii=False, indent=2)
    print(f"Updated: {FINAL_FILE}")


def print_stats(articles):
    """통계 출력"""
    content_lengths = [len(a["content"]) for a in articles]
    avg_len = sum(content_lengths) / len(content_lengths) if content_lengths else 0

    arts_with_paragraphs = sum(1 for a in articles if len(a.get("paragraphs", [])) > 1)
    total_paragraphs = sum(len(a.get("paragraphs", [])) for a in articles)

    parts = set(a.get("part", "") for a in articles if a.get("part"))
    chapters = set(a.get("chapter", "") for a in articles if a.get("chapter"))

    print(f"\n{'='*60}")
    print(f"크롤링 결과 통계")
    print(f"{'='*60}")
    print(f"총 조문 수: {len(articles)}")
    print(f"평균 content 길이: {avg_len:.0f}자")
    print(f"최소 content: {min(content_lengths)}자")
    print(f"최대 content: {max(content_lengths)}자")
    print(f"다중항 조문: {arts_with_paragraphs}건")
    print(f"총 항 수: {total_paragraphs}건")
    print(f"편 수: {len(parts)}")
    print(f"장 수: {len(chapters)}")

    # PDF 아티팩트 체크
    artifacts = sum(1 for a in articles if ".indd" in a["content"] or "복사본" in a["content"])
    print(f"PDF 아티팩트: {artifacts}건 (0이어야 정상)")

    # 샘플 출력
    print(f"\n{'='*60}")
    print(f"샘플 조문")
    print(f"{'='*60}")
    for num in [3, 42, 101, 130, 301, 618]:
        for a in articles:
            m = re.match(r"제(\d+)조$", a["article_number"])
            if m and int(m.group(1)) == num:
                print(f"\n--- {a['article_number']} ({a['title']}) [{a.get('chapter','')}] ---")
                print(f"  길이: {len(a['content'])}자, 항: {len(a.get('paragraphs',[]))}개")
                print(f"  content: {a['content'][:200]}...")
                break


if __name__ == "__main__":
    articles = crawl_articles()
    if not articles:
        print("ERROR: No articles crawled!")
        sys.exit(1)

    print_stats(articles)
    save_articles(articles)
    print("\nDone!")
