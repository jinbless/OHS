from app.integrations.prompts.prompt_builder import build_system_prompt

# Phase 4: 온톨로지 JSON 기반 동적 생성 (hazard_taxonomy.json + article_chapters.json)
SYSTEM_PROMPT = build_system_prompt()

IMAGE_ANALYSIS_PROMPT = """이 작업현장 이미지를 분석하여 산업재해 위험요소를 식별해주세요.

작업장 유형: {workplace_type}
추가 정보: {additional_context}

이미지에서 보이는 모든 잠재적 위험요소를 상세히 분석하고,
각 위험요소에 대한 예방 조치와 점검 항목을 제시해주세요."""

TEXT_ANALYSIS_PROMPT = """다음 작업 상황에서 발생할 수 있는 산업재해 위험요소를 분석해주세요.

상황 설명: {description}
작업장 유형: {workplace_type}
산업 분야: {industry_sector}

설명된 상황에서 발생 가능한 모든 위험요소를 식별하고,
각 위험요소에 대한 예방 조치와 점검 항목을 제시해주세요."""
