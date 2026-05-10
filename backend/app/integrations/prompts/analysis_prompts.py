from app.integrations.prompts.prompt_builder import build_system_prompt

SYSTEM_PROMPT = build_system_prompt()

IMAGE_ANALYSIS_PROMPT = """Analyze the workplace image as an observation extractor.

Workplace type: {workplace_type}
Additional context: {additional_context}

Return only what is visible or strongly implied by visible evidence:
- visual_observations: factual observations
- visual_cues: short matching cues such as missing guardrail, exposed cable, wet floor
- risk_feature_candidates: candidate accident type, hazardous agent, or work context

Do not choose legal articles, penalties, KOSHA guide numbers, or final violations."""

TEXT_ANALYSIS_PROMPT = """Analyze the workplace description as an observation extractor.

Description: {description}
Workplace type: {workplace_type}
Industry sector: {industry_sector}

Return only observable facts and risk feature candidates:
- visual_observations
- visual_cues
- risk_feature_candidates

Do not choose legal articles, penalties, KOSHA guide numbers, or final violations."""
