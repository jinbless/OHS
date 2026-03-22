"""포르투갈어 번역 스크립트.

norm_statements, kosha_guides 제목, 법조항 제목을 GPT-4.1-mini로 번역하여
별도 PT 테이블에 저장한다.
"""
import os
import sys
import json
import sqlite3
import time
import re
from pathlib import Path
from openai import OpenAI

# DB 경로
DB_PATH = os.environ.get("DB_PATH", "/app/data/ohs.db")
client = OpenAI(api_key=os.environ.get("OPENAI_API_KEY"))
MODEL = "gpt-4.1-mini"


def create_pt_tables(conn: sqlite3.Connection):
    """포르투갈어 번역 테이블 생성"""
    cur = conn.cursor()

    cur.execute("""
        CREATE TABLE IF NOT EXISTS norm_statements_pt (
            id INTEGER PRIMARY KEY,
            original_id INTEGER NOT NULL UNIQUE,
            article_number VARCHAR(30) NOT NULL,
            article_number_pt VARCHAR(30),
            paragraph VARCHAR(20),
            statement_order INTEGER NOT NULL,
            subject_role TEXT,
            action TEXT,
            object TEXT,
            condition_text TEXT,
            legal_effect VARCHAR(20) NOT NULL,
            effect_description TEXT,
            full_text TEXT NOT NULL,
            norm_category VARCHAR(20)
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS kosha_guides_pt (
            id INTEGER PRIMARY KEY,
            original_id INTEGER NOT NULL UNIQUE,
            guide_code VARCHAR(30) NOT NULL,
            title TEXT NOT NULL
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS article_titles_pt (
            article_number VARCHAR(30) PRIMARY KEY,
            article_number_pt VARCHAR(30),
            title_ko TEXT,
            title_pt TEXT NOT NULL
        )
    """)

    conn.commit()
    print("PT tables created.")


def convert_article_number(art_num: str) -> str:
    """제42조 → Art. 42, 제42조의2 → Art. 42-2"""
    m = re.match(r'제(\d+)조(?:의(\d+))?', art_num)
    if m:
        num = m.group(1)
        sub = m.group(2)
        if sub:
            return f"Art. {num}-{sub}"
        return f"Art. {num}"
    return art_num


def convert_paragraph(para: str) -> str:
    """제1항 → §1, 제2항 → §2"""
    if not para:
        return para
    m = re.match(r'제(\d+)항', para)
    if m:
        return f"§{m.group(1)}"
    return para


def translate_batch(texts: list[dict], context: str = "norms") -> list[dict]:
    """배치 번역: Korean → Portuguese"""
    if not texts:
        return []

    if context == "norms":
        system_msg = (
            "You are a professional translator specializing in Korean occupational safety "
            "and health (산업안전보건) law. Translate the given Korean OHS norm statements "
            "to Brazilian Portuguese. Maintain legal/technical precision. "
            "Return a JSON array with the same structure but translated fields."
        )
        user_msg = (
            "Translate each field (subject_role, action, object, condition_text, "
            "effect_description, full_text) from Korean to Portuguese. "
            "Keep 'id' and 'legal_effect' unchanged. "
            "If a field is null, keep it null.\n\n"
            f"```json\n{json.dumps(texts, ensure_ascii=False)}\n```"
        )
    elif context == "guides":
        system_msg = (
            "You are a professional translator for Korean OHS (산업안전보건) technical guides. "
            "Translate guide titles from Korean to Brazilian Portuguese. "
            "Return a JSON array with {id, title_pt}."
        )
        user_msg = (
            "Translate each title to Portuguese.\n\n"
            f"```json\n{json.dumps(texts, ensure_ascii=False)}\n```"
        )
    elif context == "articles":
        system_msg = (
            "You are a professional translator for Korean OHS (산업안전보건) law articles. "
            "Translate article titles from Korean to Brazilian Portuguese. "
            "Return a JSON array with {article_number, title_pt}."
        )
        user_msg = (
            "Translate each title to Portuguese.\n\n"
            f"```json\n{json.dumps(texts, ensure_ascii=False)}\n```"
        )

    for attempt in range(3):
        try:
            resp = client.chat.completions.create(
                model=MODEL,
                messages=[
                    {"role": "system", "content": system_msg},
                    {"role": "user", "content": user_msg},
                ],
                response_format={"type": "json_object"},
                temperature=0.2,
                max_tokens=16000,
            )
            content = resp.choices[0].message.content
            data = json.loads(content)
            # JSON object wrapping array
            if isinstance(data, dict):
                for v in data.values():
                    if isinstance(v, list):
                        return v
                return [data]
            return data
        except Exception as e:
            print(f"  Retry {attempt+1}/3: {e}")
            time.sleep(2)
    return []


def translate_norms(conn: sqlite3.Connection):
    """norm_statements 번역"""
    cur = conn.cursor()

    # 이미 번역된 ID
    cur.execute("SELECT original_id FROM norm_statements_pt")
    done_ids = set(r[0] for r in cur.fetchall())

    cur.execute("""
        SELECT id, article_number, paragraph, statement_order,
               subject_role, action, object, condition_text,
               legal_effect, effect_description, full_text, norm_category
        FROM norm_statements ORDER BY id
    """)
    rows = cur.fetchall()

    pending = [r for r in rows if r[0] not in done_ids]
    print(f"Norms: {len(rows)} total, {len(done_ids)} done, {len(pending)} to translate")

    BATCH_SIZE = 20
    for i in range(0, len(pending), BATCH_SIZE):
        batch = pending[i:i+BATCH_SIZE]
        batch_data = []
        for r in batch:
            batch_data.append({
                "id": r[0],
                "legal_effect": r[8],
                "subject_role": r[4],
                "action": r[5],
                "object": r[6],
                "condition_text": r[7],
                "effect_description": r[9],
                "full_text": r[10],
            })

        translated = translate_batch(batch_data, "norms")

        if len(translated) != len(batch):
            print(f"  WARNING: batch {i//BATCH_SIZE} returned {len(translated)} vs {len(batch)}")
            # Try one by one for mismatched batches
            if len(translated) == 0:
                continue

        # Map by id
        trans_map = {t["id"]: t for t in translated if "id" in t}

        for r in batch:
            orig_id = r[0]
            t = trans_map.get(orig_id, {})
            art_pt = convert_article_number(r[1])
            para_pt = convert_paragraph(r[2])
            cur.execute("""
                INSERT OR REPLACE INTO norm_statements_pt
                (original_id, article_number, article_number_pt, paragraph,
                 statement_order, subject_role, action, object, condition_text,
                 legal_effect, effect_description, full_text, norm_category)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                orig_id, r[1], art_pt, para_pt, r[3],
                t.get("subject_role", r[4]),
                t.get("action", r[5]),
                t.get("object", r[6]),
                t.get("condition_text", r[7]),
                r[8],  # legal_effect unchanged
                t.get("effect_description", r[9]),
                t.get("full_text", r[10]),
                r[11],  # norm_category unchanged
            ))

        conn.commit()
        done = min(i + BATCH_SIZE, len(pending))
        print(f"  Norms: {done}/{len(pending)} translated")
        time.sleep(0.3)


def translate_guides(conn: sqlite3.Connection):
    """kosha_guides 제목 번역"""
    cur = conn.cursor()

    cur.execute("SELECT original_id FROM kosha_guides_pt")
    done_ids = set(r[0] for r in cur.fetchall())

    cur.execute("SELECT id, guide_code, title FROM kosha_guides ORDER BY id")
    rows = cur.fetchall()

    pending = [r for r in rows if r[0] not in done_ids]
    print(f"Guides: {len(rows)} total, {len(done_ids)} done, {len(pending)} to translate")

    BATCH_SIZE = 50
    for i in range(0, len(pending), BATCH_SIZE):
        batch = pending[i:i+BATCH_SIZE]
        batch_data = [{"id": r[0], "title": r[2]} for r in batch]

        translated = translate_batch(batch_data, "guides")
        trans_map = {t["id"]: t for t in translated if "id" in t}

        for r in batch:
            t = trans_map.get(r[0], {})
            cur.execute("""
                INSERT OR REPLACE INTO kosha_guides_pt
                (original_id, guide_code, title)
                VALUES (?, ?, ?)
            """, (r[0], r[1], t.get("title_pt", r[2])))

        conn.commit()
        done = min(i + BATCH_SIZE, len(pending))
        print(f"  Guides: {done}/{len(pending)} translated")
        time.sleep(0.3)


def translate_article_titles(conn: sqlite3.Connection):
    """법조항 제목 번역 (ChromaDB의 article titles)"""
    cur = conn.cursor()

    cur.execute("SELECT article_number FROM article_titles_pt")
    done_arts = set(r[0] for r in cur.fetchall())

    # norm_statements에 있는 unique article_numbers
    cur.execute("SELECT DISTINCT article_number FROM norm_statements ORDER BY article_number")
    all_arts = [r[0] for r in cur.fetchall()]

    # ChromaDB에서 제목 가져오기
    sys.path.insert(0, "/app")
    from app.services.article_service import article_service

    articles_with_titles = []
    for art_num in all_arts:
        if art_num in done_arts:
            continue
        info = article_service._find_article_by_number(art_num)
        title = info["title"] if info else ""
        articles_with_titles.append({"article_number": art_num, "title_ko": title})

    print(f"Article titles: {len(all_arts)} total, {len(done_arts)} done, {len(articles_with_titles)} to translate")

    BATCH_SIZE = 50
    for i in range(0, len(articles_with_titles), BATCH_SIZE):
        batch = articles_with_titles[i:i+BATCH_SIZE]
        batch_data = [{"article_number": a["article_number"], "title": a["title_ko"]} for a in batch]

        translated = translate_batch(batch_data, "articles")
        trans_map = {t["article_number"]: t for t in translated if "article_number" in t}

        for a in batch:
            t = trans_map.get(a["article_number"], {})
            art_pt = convert_article_number(a["article_number"])
            cur.execute("""
                INSERT OR REPLACE INTO article_titles_pt
                (article_number, article_number_pt, title_ko, title_pt)
                VALUES (?, ?, ?, ?)
            """, (a["article_number"], art_pt, a["title_ko"], t.get("title_pt", a["title_ko"])))

        conn.commit()
        done = min(i + BATCH_SIZE, len(articles_with_titles))
        print(f"  Articles: {done}/{len(articles_with_titles)} translated")
        time.sleep(0.3)


def main():
    conn = sqlite3.connect(DB_PATH)
    create_pt_tables(conn)

    print("\n=== Phase 1: Translate norm statements ===")
    translate_norms(conn)

    print("\n=== Phase 2: Translate guide titles ===")
    translate_guides(conn)

    print("\n=== Phase 3: Translate article titles ===")
    translate_article_titles(conn)

    # Summary
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM norm_statements_pt")
    n1 = cur.fetchone()[0]
    cur.execute("SELECT COUNT(*) FROM kosha_guides_pt")
    n2 = cur.fetchone()[0]
    cur.execute("SELECT COUNT(*) FROM article_titles_pt")
    n3 = cur.fetchone()[0]

    print(f"\n=== DONE ===")
    print(f"  norm_statements_pt: {n1}")
    print(f"  kosha_guides_pt: {n2}")
    print(f"  article_titles_pt: {n3}")

    conn.close()


if __name__ == "__main__":
    main()
