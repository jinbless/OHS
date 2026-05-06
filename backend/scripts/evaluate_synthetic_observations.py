#!/usr/bin/env python3
"""합성 관찰사실 테스트셋으로 SHE/SR/Guide 추천 baseline을 평가한다.

이 스크립트는 실제 사진 앞단(Vision LLM)을 건너뛰고, Claude 등이 만든
구조화 관찰사실(JSONL)을 후단 파이프라인에 넣어 현재 온톨로지/추천
흐름의 약점을 찾기 위한 도구다.
"""
from __future__ import annotations

import argparse
import csv
import json
import logging
import os
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

os.environ.setdefault("OHS_ENABLE_SHE", "true")

BACKEND_DIR = Path(__file__).resolve().parents[1]
PROJECT_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(BACKEND_DIR))

from app.db.database import SessionLocal  # noqa: E402
from app.services import hazard_rule_engine, she_matcher  # noqa: E402
from app.services.industry_context import infer_industry_context  # noqa: E402

logging.getLogger("app.services.she_matcher").setLevel(logging.ERROR)

FEATURE_ENUMS = {
    "accident_types": {
        "FALL", "SLIP", "COLLISION", "FALLING_OBJECT", "CRUSH", "CUT",
        "COLLAPSE", "ERGONOMIC", "BURN", "ELECTRIC_SHOCK", "EXPLOSION",
        "CHEMICAL_EXPOSURE", "COLD_EXPOSURE", "FOOD_CONTAMINATION",
    },
    "hazardous_agents": {
        "CHEMICAL", "DUST", "TOXIC", "CORROSION", "RADIATION", "FIRE",
        "ELECTRICITY", "ARC_FLASH", "NOISE", "HEAT_COLD", "BIOLOGICAL",
    },
    "work_contexts": {
        "SCAFFOLD", "CONFINED_SPACE", "EXCAVATION", "MACHINE", "VEHICLE",
        "CRANE", "CONVEYOR", "ROBOT", "CONSTRUCTION_EQUIP", "RAIL",
        "PRESSURE_VESSEL", "STEELWORK", "MATERIAL_HANDLING",
        "GENERAL_WORKPLACE", "DEMOLITION", "PAINTING", "GRINDING",
        "ROPE_ACCESS", "ELECTRICAL_WORK", "CHEMICAL_WORK", "WELDING",
        "LADDER", "KITCHEN_COOKING", "FOOD_PREP", "DEEP_FRYING",
        "GAS_APPLIANCE", "HOT_BEVERAGE", "CLEANING_WET", "COLD_STORAGE",
        "SERVING_FLOOR", "DELIVERY_RIDER", "STORAGE_SHELF",
        "LIFT_WORK", "OIL_DRAIN", "TIRE_CHANGE", "WELDING_REPAIR",
        "EV_BATTERY", "HAIR_CHEMICAL", "NAIL_CHEMICAL", "HOT_TOOL",
        "SKIN_DEVICE", "HAIR_WASH", "SHELF_STOCKING", "NIGHT_SOLO",
        "COLD_DISPLAY", "BOX_HANDLING", "CASHIER_AREA", "SAWING",
        "SANDING", "PAINTING_WOODWORK", "LADDER_INTERIOR", "NAIL_GUN",
        "DRY_CLEANING_SOLVENT", "PRESS_MACHINE", "WASHING_MACHINE",
        "STEAM_IRON", "CHEMICAL_SPOTTING", "GARMENT_SORTING",
        "HIGH_PRESSURE_WASH", "CHEMICAL_APPLICATION", "WAX_POLISHING",
        "CONVEYOR_WASH", "INTERIOR_CLEANING", "WET_FLOOR_WORK",
        "DOG_GROOMING", "CAT_HANDLING", "PET_BATHING", "DRYER_OPERATION",
        "CAGE_CLEANING", "ANIMAL_FEEDING", "FORKLIFT_OPERATION",
        "HEAVY_LIFTING", "HIGH_SHELF_WORK", "LOADING_DOCK",
        "PACKAGE_SORTING", "CONVEYOR_BELT", "PESTICIDE_SPRAY",
        "FARM_MACHINERY", "GREENHOUSE_WORK", "HARVEST_WORK", "IRRIGATION",
        "FERTILIZER_HANDLING", "ELECTRICAL_OVERLOAD", "FIRE_EVACUATION",
        "VENTILATION_POOR", "CLEANING_NIGHT", "CROWD_MANAGEMENT",
        "NOISE_EXPOSURE", "FUEL_DISPENSING", "STATIC_ELECTRICITY",
        "FUEL_SPILL", "UNDERGROUND_TANK", "VAPOR_EXPOSURE",
        "NIGHT_SOLO_WORK",
    },
    "ppe_states": {
        "HELMET_WORN", "HELMET_MISSING", "HARNESS_TIED", "HARNESS_UNTIED",
        "HARNESS_WORN", "HARNESS_MISSING", "GLOVE_WORN", "GLOVES_MISSING",
        "MASK_WORN", "MASK_MISSING", "GOGGLES_WORN", "GOGGLES_MISSING",
        "VEST_WORN", "VEST_MISSING", "SAFETY_SHOES_WORN",
        "SAFETY_SHOES_MISSING", "OTHER",
    },
    "environmental": {
        "WET_SURFACE", "OIL_CONTAMINATION", "HIGH_ELEVATION", "LOW_LIGHT",
        "CLUTTERED", "WINDY_WEATHER", "EXTREME_TEMPERATURE",
        "NARROW_SPACE", "UNSTABLE_GROUND", "OTHER",
    },
}

UNSUPPORTED_FEATURE_ALIASES = {
    "work_contexts": {
        # 현재 온톨로지에서는 용접이 work_context가 아니라 작업활동/상황 단서에 가깝다.
        "PRESSURIZED_WORK": "PRESSURE_VESSEL",
        "ELECTRICITY_WORK": "ELECTRICAL_WORK",
    },
    "environmental": {
        "습기": "WET_SURFACE",
        "미끄러운_바닥": "WET_SURFACE",
        "우천": "WET_SURFACE",
        "미끄러운_도로": "WET_SURFACE",
        "저온": "EXTREME_TEMPERATURE",
        "LOW_TEMPERATURE": "EXTREME_TEMPERATURE",
        "고온_기름": "EXTREME_TEMPERATURE",
        "고온_스팀": "EXTREME_TEMPERATURE",
        "고온_음료": "EXTREME_TEMPERATURE",
        "고온_증기": "EXTREME_TEMPERATURE",
        "조명_불량": "LOW_LIGHT",
        "야간": "LOW_LIGHT",
        "시야_차단": "LOW_LIGHT",
        "좁은_주방": "NARROW_SPACE",
        "좁은_전처리실": "NARROW_SPACE",
        "좁은_통로": "NARROW_SPACE",
        "좁은_도로": "NARROW_SPACE",
        "좁은_공간": "NARROW_SPACE",
        "통행_동선": "NARROW_SPACE",
        "정리정돈_완비": "OTHER",
        "전처리_작업대": "OTHER",
        "전동_조리기구": "OTHER",
        "도로": "OTHER",
        "인도": "OTHER",
        "보행자_밀집": "OTHER",
        "자전거도로": "OTHER",
        "무인_주방": "OTHER",
        "단독_작업": "OTHER",
        "유기용제": "OTHER",
        "유기용제_누출": "OTHER",
        "유기용제_누출_위험": "OTHER",
        "정리정돈_완비": "OTHER",
        "생물학적_위험": "OTHER",
        "동물_교상_위험": "OTHER",
        "동물_복지": "OTHER",
        "주유소 주유 구역": "OTHER",
        "주유소 차량 내외부": "OTHER",
        "주유소 바닥": "OTHER",
        "주유소 캐노피": "OTHER",
        "주유소 캐노피 근무": "OTHER",
        "주유소 이송 작업": "OTHER",
        "심야 주유소": "LOW_LIGHT",
        "야간 주유소 점검 구역": "LOW_LIGHT",
        "야간 PC방 타일 바닥": "LOW_LIGHT",
        "밀폐 세차장": "NARROW_SPACE",
        "노래방 부스 밀폐": "NARROW_SPACE",
        "밀폐 노래방": "NARROW_SPACE",
        "노래방 룸 밀폐": "NARROW_SPACE",
        "지하 밀폐 PC방": "NARROW_SPACE",
        "온실 밀폐 공간": "NARROW_SPACE",
        "온실 밀폐 고온": "EXTREME_TEMPERATURE",
        "온실 습윤 바닥": "WET_SURFACE",
        "고온": "EXTREME_TEMPERATURE",
        "고온_드라이어": "EXTREME_TEMPERATURE",
        "고온_세탁물": "EXTREME_TEMPERATURE",
        "고온_표면": "EXTREME_TEMPERATURE",
        "고온_증기": "EXTREME_TEMPERATURE",
        "고압_세척기": "OTHER",
        "화학_약품": "OTHER",
        "화학_약품_노출": "OTHER",
        "화학_약품_보관": "OTHER",
        "기계_이동": "OTHER",
        "프레스_기계": "OTHER",
        "회전_기계": "OTHER",
        "컨베이어_벨트": "OTHER",
        "지게차": "OTHER",
        "지게차_작업": "OTHER",
        "하역_도크": "OTHER",
        "창고 실내": "OTHER",
        "선반": "OTHER",
        "선반_과적": "OTHER",
        "선반_고정_불량": "OTHER",
        "과적_팔레트": "OTHER",
        "과하중": "OTHER",
        "이동식_발판": "OTHER",
        "차량": "OTHER",
        "야외 농경지": "OTHER",
        "농경지 야외": "OTHER",
        "농경지 작업 현장": "OTHER",
        "농경지": "OTHER",
        "농경지 통로": "OTHER",
        "과수원 야외 경사지": "UNSTABLE_GROUND",
        "경사 농로": "UNSTABLE_GROUND",
        "경사 논두렁": "UNSTABLE_GROUND",
        "경사로": "UNSTABLE_GROUND",
        "야외 도랑": "UNSTABLE_GROUND",
        "굴착 도랑 내부": "UNSTABLE_GROUND",
        "농경지 관개 시설": "OTHER",
        "수로·물가": "WET_SURFACE",
        "야간 수로": "LOW_LIGHT",
        "바람 노출": "WINDY_WEATHER",
        "PC방 실내": "OTHER",
        "PC방 통로": "NARROW_SPACE",
        "PC방 전기실": "OTHER",
        "PC방 비상구": "OTHER",
        "PC방 복도": "NARROW_SPACE",
        "PC방 서버실": "NARROW_SPACE",
        "PC방 공조실": "NARROW_SPACE",
        "PC방 PC 주변": "OTHER",
        "PC방 영업 종료 후": "LOW_LIGHT",
        "PC방 영업 중": "OTHER",
        "PC방 계단": "UNSTABLE_GROUND",
        "PC방 입구": "OTHER",
        "서버실": "NARROW_SPACE",
        "노래방 복도": "NARROW_SPACE",
        "노래방 카운터": "OTHER",
        "노래방 내부": "NARROW_SPACE",
        "노래방 화장실": "WET_SURFACE",
        "노래방 + 외부 공사 소음": "OTHER",
        "노래방 룸": "NARROW_SPACE",
        "지하 탱크 맨홀": "NARROW_SPACE",
        "지하 탱크 점검구": "NARROW_SPACE",
        "주유소 지하 탱크": "NARROW_SPACE",
        "주유기 내부 작업": "OTHER",
        "주유소 배수로": "OTHER",
        "주유소 쓰레기통": "OTHER",
        "주유소 임시 보관": "OTHER",
        "물탱크 상부": "HIGH_ELEVATION",
        "야외 작업": "OTHER",
        "창고 야외": "OTHER",
        "전선_노출": "OTHER",
        "전동_공구": "OTHER",
        "전기_과부하": "OTHER",
        "비상구_차단": "OTHER",
        "날카로운_공구": "OTHER",
        "날카로운_부착물": "OTHER",
        "날카로운_모서리": "OTHER",
        "개방_배수구": "UNSTABLE_GROUND",
        "동물_낙하_위험": "OTHER",
        "소음": "OTHER",
    }
}

CROSS_FIELD_ALIASES = {
    ("accident_types", "FIRE"): ("hazardous_agents", "FIRE"),
    ("accident_types", "EXPLOSION"): ("hazardous_agents", "FIRE"),
    ("accident_types", "BURN"): ("hazardous_agents", "HEAT_COLD"),
    ("accident_types", "COLD_EXPOSURE"): ("hazardous_agents", "HEAT_COLD"),
    ("accident_types", "ELECTRIC_SHOCK"): ("hazardous_agents", "ELECTRICITY"),
    ("accident_types", "CHEMICAL_EXPOSURE"): ("hazardous_agents", "CHEMICAL"),
    ("accident_types", "FOOD_CONTAMINATION"): ("hazardous_agents", "BIOLOGICAL"),
    ("accident_types", "RADIATION_EXPOSURE"): ("hazardous_agents", "RADIATION"),
    ("accident_types", "ARC_FLASH"): ("hazardous_agents", "ARC_FLASH"),
    ("environmental", "CONFINED_SPACE"): ("work_contexts", "CONFINED_SPACE"),
    ("environmental", "밀폐_공간"): ("work_contexts", "CONFINED_SPACE"),
    ("environmental", "밀폐_주방"): ("work_contexts", "CONFINED_SPACE"),
    ("environmental", "환기_불량"): ("work_contexts", "CONFINED_SPACE"),
    ("environmental", "가스_누출_위험"): ("hazardous_agents", "FIRE"),
    ("environmental", "가스_화기"): ("hazardous_agents", "FIRE"),
    ("environmental", "화기"): ("hazardous_agents", "FIRE"),
    ("environmental", "화기_구역"): ("hazardous_agents", "FIRE"),
    ("environmental", "인화성_물질_근접"): ("hazardous_agents", "FIRE"),
    ("environmental", "인화성_물질"): ("hazardous_agents", "FIRE"),
    ("environmental", "초기화재"): ("hazardous_agents", "FIRE"),
    ("environmental", "소화기_미사용"): ("hazardous_agents", "FIRE"),
    ("environmental", "소화_설비_미비"): ("hazardous_agents", "FIRE"),
    ("environmental", "소화_설비_차단"): ("hazardous_agents", "FIRE"),
    ("environmental", "고압"): ("hazardous_agents", "FIRE"),
    ("environmental", "연기"): ("hazardous_agents", "FIRE"),
    ("environmental", "전기_기구"): ("hazardous_agents", "ELECTRICITY"),
    ("environmental", "주방_전기_설비"): ("hazardous_agents", "ELECTRICITY"),
    ("environmental", "전선_노출"): ("hazardous_agents", "ELECTRICITY"),
    ("environmental", "CO_위험"): ("hazardous_agents", "TOXIC"),
    ("environmental", "배기가스"): ("hazardous_agents", "TOXIC"),
    ("environmental", "화학_물질"): ("hazardous_agents", "CHEMICAL"),
    ("environmental", "식품_위생"): ("accident_types", "FOOD_CONTAMINATION"),
    ("environmental", "비상구_차단"): ("accident_types", "COLLISION"),
    ("environmental", "선반_적재"): ("accident_types", "FALLING_OBJECT"),
    ("environmental", "과적_선반"): ("accident_types", "FALLING_OBJECT"),
    ("environmental", "계단"): ("accident_types", "FALL"),
    ("environmental", "경사로"): ("accident_types", "FALL"),
    ("environmental", "고소_작업"): ("accident_types", "FALL"),
    ("environmental", "리프트_하부_작업"): ("work_contexts", "LIFT_WORK"),
    ("environmental", "리프트_작동_중"): ("work_contexts", "LIFT_WORK"),
    ("environmental", "리프트_과하중"): ("work_contexts", "LIFT_WORK"),
    ("environmental", "차량_하부_작업"): ("work_contexts", "LIFT_WORK"),
    ("environmental", "고압_공기"): ("work_contexts", "TIRE_CHANGE"),
    ("environmental", "고온_오일"): ("hazardous_agents", "HEAT_COLD"),
    ("environmental", "가압_냉각수"): ("hazardous_agents", "HEAT_COLD"),
    ("environmental", "오일_바닥_오염"): ("environmental", "OIL_CONTAMINATION"),
    ("environmental", "용접_흄"): ("hazardous_agents", "TOXIC"),
    ("environmental", "고전압_배터리"): ("hazardous_agents", "ELECTRICITY"),
    ("environmental", "화학_약품_취급"): ("hazardous_agents", "CHEMICAL"),
    ("environmental", "분진"): ("hazardous_agents", "DUST"),
    ("environmental", "자외선_방사"): ("hazardous_agents", "RADIATION"),
    ("environmental", "레이저_방사"): ("hazardous_agents", "RADIATION"),
    ("environmental", "광_방사"): ("hazardous_agents", "RADIATION"),
    ("environmental", "고온_도구"): ("hazardous_agents", "HEAT_COLD"),
    ("environmental", "고온_샴푸"): ("hazardous_agents", "HEAT_COLD"),
    ("environmental", "인체공학적_위험"): ("accident_types", "ERGONOMIC"),
    ("environmental", "전동_공구"): ("work_contexts", "MACHINE"),
    ("environmental", "공압_공구"): ("work_contexts", "MACHINE"),
    ("environmental", "화재_위험"): ("hazardous_agents", "FIRE"),
    ("environmental", "전기_과부하"): ("hazardous_agents", "ELECTRICITY"),
    ("environmental", "선반_과적"): ("accident_types", "FALLING_OBJECT"),
    ("environmental", "고정_불량"): ("accident_types", "FALLING_OBJECT"),
    ("environmental", "판매_노출_위험"): ("hazardous_agents", "CHEMICAL"),
    ("environmental", "폭력_위험"): ("environmental", "OTHER"),
    ("environmental", "HIGH_TEMPERATURE"): ("environmental", "EXTREME_TEMPERATURE"),
    ("environmental", "POOR_LIGHTING"): ("environmental", "LOW_LIGHT"),
    ("environmental", "STRONG_WIND"): ("environmental", "WINDY_WEATHER"),
    ("ppe_states", "GLOVES_WORN"): ("ppe_states", "GLOVE_WORN"),
}

CASE_WORK_CONTEXT_ALIASES = {
    "ELECTRICITY_WORK": "ELECTRICAL_WORK",
    "ELECTRIC_WORK": "ELECTRICAL_WORK",
    "CHEMICAL_WORK": "CHEMICAL_WORK",
    "WELDING": "WELDING",
    "LADDER": "LADDER",
    "LIFT_WORK": "LIFT_WORK",
    "OIL_DRAIN": "OIL_DRAIN",
    "TIRE_CHANGE": "TIRE_CHANGE",
    "WELDING_REPAIR": "WELDING_REPAIR",
    "EV_BATTERY": "EV_BATTERY",
    "HAIR_CHEMICAL": "HAIR_CHEMICAL",
    "NAIL_CHEMICAL": "NAIL_CHEMICAL",
    "HOT_TOOL": "HOT_TOOL",
    "SKIN_DEVICE": "SKIN_DEVICE",
    "HAIR_WASH": "HAIR_WASH",
    "SHELF_STOCKING": "SHELF_STOCKING",
    "NIGHT_SOLO": "NIGHT_SOLO",
    "COLD_DISPLAY": "COLD_DISPLAY",
    "BOX_HANDLING": "BOX_HANDLING",
    "CASHIER_AREA": "CASHIER_AREA",
    "SAWING": "SAWING",
    "SANDING": "SANDING",
    "PAINTING_WOODWORK": "PAINTING_WOODWORK",
    "LADDER_INTERIOR": "LADDER_INTERIOR",
    "NAIL_GUN": "NAIL_GUN",
    # v8 industry-specific contexts folded into the current ontology vocabulary.
    "PESTICIDE_APPLICATION": "PESTICIDE_SPRAY",
    "ORCHARD_LADDER": "LADDER",
    "TUNNEL_SUPPORT": "EXCAVATION",
    "SHAFT_HOIST": "CRANE",
    "COMPACTOR_OPERATION": "MACHINE",
    "SHREDDER_OPERATION": "MACHINE",
    "TRUCK_COUPLING": "VEHICLE",
    "PLANER_JOINTER": "SAWING",
    "SEWING_MACHINE": "MACHINE",
    "NEEDLE_BROKEN": "MACHINE",
    "YARN_WINDING": "MACHINE",
    "PAPER_CUTTING": "MACHINE",
    "NEEDLESTICK": "MATERIAL_HANDLING",
    "PATIENT_TRANSFER": "GENERAL_WORKPLACE",
    "MEDICAL_WASTE": "MATERIAL_HANDLING",
    "MEDICATION_HANDLING": "MATERIAL_HANDLING",
    "DYEING_FINISHING": "CHEMICAL_WORK",
    "SOLVENT_CLEANING": "CHEMICAL_WORK",
    "CHEMICAL_MIXING": "CHEMICAL_WORK",
    "SCALDING_DEHAIRING": "MACHINE",
    "CONVEYOR_HOOK": "CONVEYOR_BELT",
    "CARDIO_EQUIPMENT": "MACHINE",
    "CREMATION_FURNACE": "CHEMICAL_WORK",
}

V5_WORK_CONTEXTS = [
    "DRY_CLEANING_SOLVENT", "PRESS_MACHINE", "WASHING_MACHINE",
    "STEAM_IRON", "CHEMICAL_SPOTTING", "GARMENT_SORTING",
    "HIGH_PRESSURE_WASH", "CHEMICAL_APPLICATION", "WAX_POLISHING",
    "CONVEYOR_WASH", "INTERIOR_CLEANING", "WET_FLOOR_WORK",
    "DOG_GROOMING", "CAT_HANDLING", "PET_BATHING", "DRYER_OPERATION",
    "CAGE_CLEANING", "ANIMAL_FEEDING", "FORKLIFT_OPERATION",
    "HEAVY_LIFTING", "HIGH_SHELF_WORK", "LOADING_DOCK",
    "PACKAGE_SORTING", "CONVEYOR_BELT", "PESTICIDE_SPRAY",
    "FARM_MACHINERY", "GREENHOUSE_WORK", "HARVEST_WORK", "IRRIGATION",
    "FERTILIZER_HANDLING", "ELECTRICAL_OVERLOAD", "FIRE_EVACUATION",
    "VENTILATION_POOR", "CLEANING_NIGHT", "CROWD_MANAGEMENT",
    "NOISE_EXPOSURE", "FUEL_DISPENSING", "STATIC_ELECTRICITY",
    "FUEL_SPILL", "UNDERGROUND_TANK", "VAPOR_EXPOSURE",
    "NIGHT_SOLO_WORK",
]
CASE_WORK_CONTEXT_ALIASES.update({code: code for code in V5_WORK_CONTEXTS})

CASE_WORK_CONTEXT_ALIAS_RULES = [
    (("RADIATION_XRAY", "XRAY", "X_RAY", "X-RAY", "PLATE_MAKING", "UV_COATING"), "CHEMICAL_WORK"),
    (("EQUIPMENT_MAINTENANCE", "CHAMBER_MAINTENANCE"), "MACHINE"),
    (("COMPOUND_MIXING", "OPEN_MILL", "KNEE_BAR"), "MACHINE"),
    (("CONFINED", "TANK_ENTRY"), "CONFINED_SPACE"),
    (("SCAFFOLD",), "SCAFFOLD"),
    (("EXCAVATION", "TRENCH", "EARTH_RETAINING", "UNDERGROUND_UTILITY"), "EXCAVATION"),
    (("CRANE",), "CRANE"),
    (("FORKLIFT",), "FORKLIFT_OPERATION"),
    (("CONVEYOR",), "CONVEYOR_BELT"),
    (("LADDER",), "LADDER"),
    (("ROPE", "HIGH_RISE_WINDOW", "ROOF", "ELEVATED", "DECKING"), "ROPE_ACCESS"),
    (("WELDING",), "WELDING"),
    (("HOT_WORK",), "WELDING"),
    (("ELECTRIC", "ELECTRICAL", "HIGH_VOLTAGE", "ESD", "SOLDER"), "ELECTRICAL_WORK"),
    (("CHEMICAL", "SOLVENT", "ACID", "ETCH", "HF", "LAB_", "REACTOR", "DISTILLATION", "HAZMAT", "INK", "VULCANIZATION", "COMPOUND"), "CHEMICAL_WORK"),
    (("SPRAY_PAINT", "PAINT", "SURFACE_FINISHING", "AIRLESS"), "PAINTING"),
    (("SURFACE_PREP", "GRIND", "SANDING", "POLISH"), "GRINDING"),
    (("KNIFE",), "FOOD_PREP"),
    (("LATHE", "MILLING", "PRESS", "STAMPING", "MACHINE", "MOLD", "EXTRUSION", "SAW", "CUTTER", "SLICER", "GRINDER", "AUTOCLAVE", "STERILIZATION", "FOOD_PROCESSING", "DOUGH", "PRINTING", "FOLDING", "GUILLOTINE", "PACKAGING", "COMPACTOR", "SHREDDER", "PLANER", "JOINTER", "SEWING", "YARN", "PAPER_CUTTING"), "MACHINE"),
    (("FORMWORK", "CONCRETE", "SOIL_COMPACTION", "PUMP_OPERATION"), "CONSTRUCTION_EQUIP"),
    (("REBAR", "STEEL_ERECTION"), "STEELWORK"),
    (("PICKING",), "PACKAGE_SORTING"),
    (("RACKING",), "HIGH_SHELF_WORK"),
    (("MATERIAL", "HANDLING", "HEAVY", "BOX", "STORAGE", "LOADING", "WASTE", "LANDFILL", "RECYCLING", "BODY_TRANSPORT", "MEDICAL_WASTE", "NEEDLESTICK", "SHARPS"), "MATERIAL_HANDLING"),
    (("VEHICLE_LIFT", "ENGINE_OVERHAUL", "BRAKE_EXHAUST"), "LIFT_WORK"),
    (("TIRE_WHEEL",), "TIRE_CHANGE"),
    (("COLD", "FREEZER", "ICE"), "COLD_STORAGE"),
    (("WET", "FLOOR", "CLEANING", "RESTROOM", "SANITATION", "FISH", "POOL", "AQUACULTURE"), "WET_FLOOR_WORK"),
    (("OVEN", "HOT_TRAY", "BAKING", "KITCHEN"), "KITCHEN_COOKING"),
    (("DISPLAY", "SERVING"), "SERVING_FLOOR"),
    (("FREE_WEIGHT",), "HEAVY_LIFTING"),
    (("CARDIO", "CLIMBING", "EXERCISE"), "GENERAL_WORKPLACE"),
    (("FUNERAL", "EMBALMING", "CREMATION", "DENTAL", "CLEANROOM", "FLORAL", "OUTDOOR_PLAY"), "GENERAL_WORKPLACE"),
    (("FUEL", "GAS_STATION"), "FUEL_DISPENSING"),
    (("VENTILATION",), "VENTILATION_POOR"),
    (("NOISE",), "NOISE_EXPOSURE"),
    (("PESTICIDE", "FERTILIZER", "GREENHOUSE", "HARVEST", "IRRIGATION", "FARM"), "HARVEST_WORK"),
]


def map_case_work_context(case_work_context: str | None) -> str | None:
    code = (case_work_context or "").upper()
    if not code:
        return None
    if code in CASE_WORK_CONTEXT_ALIASES:
        return CASE_WORK_CONTEXT_ALIASES[code]
    for terms, mapped in CASE_WORK_CONTEXT_ALIAS_RULES:
        if any(term in code for term in terms):
            return mapped
    return None


TEXT_FEATURE_RULES = {
    "accident_types": [
        (("FOREIGN_OBJECT_IN_CHAMBER", "PRE_START_CHECKLIST", "KNEE_BAR", "EMERGENCY_STOP", "INTERLOCK", "GUARD_MISSING", "COVER_MISSING", "ROTATING_PART", "UNGUARDED", "덮개 이탈", "회전체 노출", "힌지 헐거움", "트레드밀", "기계 오작동", "갑작스런 작동"), "CRUSH"),
        (("SLAG_REMOVAL", "ARC_EYE", "PHOTOKERATITIS"), "BURN"),
        (("추락", "낙상", "떨어짐", "FALL_HAZARD", "FALL_RISK", "FALL_ARREST", "FALL_THROUGH", "HIGH_ALTITUDE", "고소", "로프 킹크", "킹크", "파단"), "FALL"),
        (("미끄", "SLIP", "ICY", "WET_FLOOR", "TRIP_HAZARD", "걸림", "단차", "도크 레벨러"), "SLIP"),
        (("충돌", "COLLISION", "IMPACT", "PEDESTRIAN", "BLIND_SPOT", "TRAFFIC", "타이어 마모", "마모 정도", "지게차 통과", "지게차 안정성"), "COLLISION"),
        (("낙하", "FALLING_OBJECT", "DROP_HAZARD", "LOAD_FALL", "WAFER_DROP", "FALLING_TOOL", "ROCKFALL", "SPALLING", "PROJECTILE", "와이어로프", "교차 권취", "드럼 이탈"), "FALLING_OBJECT"),
        (("끼임", "협착", "말림", "CRUSH", "ENTANGLE", "ENTANGLEMENT", "NIP", "HAND_IN", "ROTATING", "ROLLER", "PRESS", "DIE", "MOLD", "CONVEYOR", "COMPACTOR", "SHREDDER", "YARN_WINDING", "LOCKOUT_TAGOUT", "SAFETY_INTERLOCK", "BYPASS", "COUPLING_ERROR"), "CRUSH"),
        (("절단", "베임", "찔림", "CUT", "BLADE", "KNIFE", "SAW", "CUTTER", "STABBING", "IMPALEMENT", "PUNCTURE", "NEEDLESTICK", "BROKEN_NEEDLE", "SHARPS", "PROJECTILE", "칼 손잡이", "발골"), "CUT"),
        (("붕괴", "COLLAPSE", "SHORING", "FORMWORK_DISTRESS", "STRUCTURAL_FAILURE", "EARTH_RETAINING", "ROCKFALL", "GROUND_SUPPORT", "TUNNEL_SUPPORT", "UNSUPPORTED_ROOF", "SHOTCRETE", "ROCK_BOLT", "철근 간격", "설계 기준", "양생", "보양 시트", "동절기", "매설물", "시험 굴착"), "COLLAPSE"),
        (("근골격", "요통", "MSI", "ERGONOMIC", "MANUAL_LIFT", "REPETITIVE", "AWKWARD_POSTURE", "HEAVY_MANUAL", "어지러움", "창백", "의료 응급", "탈수", "과호흡"), "ERGONOMIC"),
        (("화상", "고온", "BURN", "HOT", "HEAT", "STEAM", "OVEN", "AUTOCLAVE"), "BURN"),
        (("감전", "ELECTRIC_SHOCK", "ELECTROCUTION", "HIGH_VOLTAGE", "ENERGIZED", "POWER_LINE", "ELECTRICAL_CONTACT", "UNEXPECTED_ENERGIZATION", "ESD", "접지", "정전기"), "ELECTRIC_SHOCK"),
        (("폭발", "EXPLOSION", "OVERPRESSURE", "RUNAWAY", "STATIC_SPARK", "HYDROGEN"), "EXPLOSION"),
        (("화학", "흡입", "질식", "중독", "CHEMICAL_EXPOSURE", "TOXIC", "VOC", "SOLVENT", "FUME", "GAS", "ASBESTOS", "SILICA", "HF", "ACID", "CHLORINE", "CO_POISONING", "O2_NOT", "유해가스", "유독 가스", "훈증", "훈증제", "잔류 농도"), "CHEMICAL_EXPOSURE"),
        (("한냉", "저체온", "COLD", "HYPOTHERMIA"), "COLD_EXPOSURE"),
        (("식품", "오염", "CONTAMINATION", "FOOD_CONTAMINATION", "INFECTION"), "FOOD_CONTAMINATION"),
    ],
    "hazardous_agents": [
        (("RADIATION", "X-RAY", "XRAY", "X_RAY", "UV", "ULTRAVIOLET", "LASER", "DOSIMETER", "LEAD_APRON", "SHIELDING", "SCATTERED_RADIATION", "PHOTOKERATITIS"), "RADIATION"),
        (("ARC_FLASH", "SLAG", "SLAG_REMOVAL", "ARC_EYE", "WELDING_ARC"), "ARC_FLASH"),
        (("화재", "FIRE", "IGNITION", "FLAMMABLE", "SPARK", "불꽃", "발화"), "FIRE"),
        (("감전", "전기", "ELECTRIC", "ELECTROCUTION", "HIGH_VOLTAGE", "ENERGIZED", "POWER_LINE", "ESD", "접지", "정전기"), "ELECTRICITY"),
        (("아크", "ARC_FLASH"), "ARC_FLASH"),
        (("화학", "CHEMICAL", "SOLVENT", "PESTICIDE", "FERTILIZER", "INK", "HF", "훈증", "훈증제", "파마약", "도장"), "CHEMICAL"),
        (("부식", "산성", "강알칼리", "ACID", "CORROSION"), "CORROSION"),
        (("독성", "TOXIC", "VOC", "FUME", "GAS", "CO_", "CHLORINE", "ASBESTOS", "유해가스", "유독 가스", "잔류 농도", "잔류물 연소"), "TOXIC"),
        (("분진", "DUST", "SILICA", "FLOUR", "먼지"), "DUST"),
        (("소음", "NOISE"), "NOISE"),
        (("고온", "잔열", "열", "HOT", "HEAT", "STEAM", "OVEN", "COLD", "한냉", "화장로"), "HEAT_COLD"),
        (("감염", "혈액", "BIO", "BIOLOGICAL", "INFECTION", "MEDICAL_WASTE", "SHARPS"), "BIOLOGICAL"),
    ],
    "environmental": [
        (("젖", "습기", "미끄러운", "WET", "ICY", "WATER", "SLIPPERY"), "WET_SURFACE"),
        (("기름", "OIL"), "OIL_CONTAMINATION"),
        (("고소", "높이", "HIGH_ELEVATION", "HIGH_ALTITUDE", "EDGE", "ROOF"), "HIGH_ELEVATION"),
        (("야간", "조도", "LOW_LIGHT", "LOW_ILLUMINATION", "NIGHT"), "LOW_LIGHT"),
        (("정리정돈", "CLUTTER", "OBSTRUCTION", "방치", "통로 일부", "통로 부분", "부분 차단"), "CLUTTERED"),
        (("강풍", "WIND"), "WINDY_WEATHER"),
        (("고온", "저온", "잔열", "HOT", "COLD", "SUB_ZERO", "EXTREME"), "EXTREME_TEMPERATURE"),
        (("밀폐", "협소", "CONFINED", "ENCLOSED", "NARROW"), "NARROW_SPACE"),
        (("불안정", "경사", "UNSTABLE", "SOFT_GROUND", "SETTLEMENT"), "UNSTABLE_GROUND"),
    ],
}


def _row_feature_text(row: dict[str, Any]) -> str:
    chunks: list[str] = []

    def add(value: Any) -> None:
        if value is None:
            return
        if isinstance(value, (str, int, float, bool)):
            chunks.append(str(value))
        elif isinstance(value, list):
            for item in value:
                add(item)
        elif isinstance(value, dict):
            for key, item in value.items():
                if isinstance(item, bool):
                    if item:
                        chunks.append(str(key))
                else:
                    chunks.append(str(key))
                    add(item)

    for key in (
        "work_context",
        "industry_context",
        "photo_description",
        "scene_description",
        "visual_cues",
        "uncertain_cues",
        "expected_features",
        "expected_primary_risk",
        "expected_corrective_direction",
        "false_positive_risk",
        "notes_for_evaluation",
    ):
        add(row.get(key))
    return " ".join(chunks)


def _row_description(row: dict[str, Any]) -> str:
    return str(row.get("photo_description") or row.get("scene_description") or "")


def _row_work_context(row: dict[str, Any]) -> str:
    work_contexts = (row.get("expected_features") or {}).get("work_contexts") or []
    if isinstance(work_contexts, list) and work_contexts:
        return str(work_contexts[0])
    if isinstance(work_contexts, str):
        return work_contexts
    if row.get("work_context"):
        return str(row["work_context"])
    return ""


def _normalized_expected_behavior(row: dict[str, Any]) -> dict[str, Any]:
    expected = dict(row.get("expected_pipeline_behavior") or {})
    penalty_exposure = expected.get("penalty_exposure", "NONE")
    if penalty_exposure is False or penalty_exposure is None:
        expected["penalty_exposure"] = "NONE"
    elif penalty_exposure is True:
        expected["penalty_exposure"] = "CONDITIONAL"
    else:
        expected["penalty_exposure"] = str(penalty_exposure)
    expected.setdefault("should_match_she", False)
    expected.setdefault("should_recommend_sr", False)
    expected.setdefault("preferred_action_source", "NONE")
    expected.setdefault("needs_clarification", False)
    return expected


def _add_inferred_feature(
    features: dict[str, list[str]],
    notes: list[dict[str, str]],
    field: str,
    value: str,
    source: str,
) -> None:
    if value not in FEATURE_ENUMS[field] or value in features[field]:
        return
    features[field].append(value)
    notes.append({"field": field, "from": source, "to": value, "source": "inferred_text"})


def infer_features_from_row(
    row: dict[str, Any],
    features: dict[str, list[str]],
    notes: list[dict[str, str]],
) -> None:
    expected = row.get("expected_pipeline_behavior") or {}
    if not (
        expected.get("should_match_she")
        or expected.get("should_recommend_sr")
        or expected.get("penalty_exposure") in {"DIRECT", "CONDITIONAL"}
    ):
        return

    text = _row_feature_text(row)
    text_upper = text.upper()
    for field, rules in TEXT_FEATURE_RULES.items():
        for terms, mapped in rules:
            if any(term.upper() in text_upper for term in terms):
                _add_inferred_feature(features, notes, field, mapped, "/".join(terms[:3]))

    absent_text = any(term in text_upper for term in ("ABSENT", "MISSING", "UNTIED", "미착용", "없음", "미부착", "미설치", "부재"))
    worn_text = any(term in text_upper for term in ("WORN", "TIED", "착용", "APPLIED", "설치", "체결"))

    if "HELMET" in text_upper or "안전모" in text:
        _add_inferred_feature(features, notes, "ppe_states", "HELMET_MISSING" if absent_text else "HELMET_WORN", "helmet_text")
    if any(term in text_upper for term in ("HARNESS", "FALL_ARREST", "SAFETY_HARNESS", "안전대")):
        _add_inferred_feature(features, notes, "ppe_states", "HARNESS_MISSING" if absent_text else "HARNESS_TIED", "harness_text")
    if any(term in text_upper for term in ("GLOVE", "장갑", "HEAT_PROTECTION", "CUT_RESISTANT", "INSULATION_GLOVES")):
        _add_inferred_feature(features, notes, "ppe_states", "GLOVES_MISSING" if absent_text else "GLOVE_WORN", "glove_text")
    if any(term in text_upper for term in ("MASK", "RESPIRATOR", "SCBA", "방독", "방진", "마스크")):
        _add_inferred_feature(features, notes, "ppe_states", "MASK_MISSING" if absent_text else "MASK_WORN", "mask_text")
    if any(term in text_upper for term in ("GOGGLE", "EYE_PROTECTION", "FACE_SHIELD", "보안경", "안면 보호")):
        _add_inferred_feature(features, notes, "ppe_states", "GOGGLES_MISSING" if absent_text else "GOGGLES_WORN", "eye_protection_text")
    if any(term in text_upper for term in ("SAFETY_SHOE", "SLIP_PROTECTION", "안전화")):
        _add_inferred_feature(features, notes, "ppe_states", "SAFETY_SHOES_MISSING" if absent_text else "SAFETY_SHOES_WORN", "safety_shoe_text")
    if "VEST" in text_upper:
        _add_inferred_feature(features, notes, "ppe_states", "VEST_MISSING" if absent_text else "VEST_WORN", "vest_text")

    if absent_text and not features["ppe_states"]:
        _add_inferred_feature(features, notes, "ppe_states", "GOGGLES_MISSING", "generic_ppe_absent")

UNSUPPORTED_FEATURE_ALIASES.setdefault("ppe_states", {}).update({
    "없음": "OTHER",
    "GLOVES_WORN": "GLOVE_WORN",
    "방독마스크 미착용": "MASK_MISSING",
    "방진마스크 미착용": "MASK_MISSING",
    "마스크 미착용": "MASK_MISSING",
    "마스크 없음": "MASK_MISSING",
    "유기 가스용 마스크 미착용": "MASK_MISSING",
    "방독마스크 착용": "MASK_WORN",
    "마스크 착용 (종류 불명)": "OTHER",
    "안전대 미착용": "HARNESS_MISSING",
    "안전벨트 미착용": "HARNESS_MISSING",
    "안전대 착용": "HARNESS_TIED",
    "절연 장갑 미착용": "GLOVES_MISSING",
    "장갑 미착용": "GLOVES_MISSING",
    "보호 장갑 미착용": "GLOVES_MISSING",
    "장갑 탈의 중": "GLOVES_MISSING",
    "장갑 착용 여부 미확인": "OTHER",
    "방연 장갑 미착용": "GLOVES_MISSING",
    "보안경 미착용": "GOGGLES_MISSING",
    "보안경 착용 여부 미확인": "OTHER",
    "안전모 미착용": "HELMET_MISSING",
    "안전모 없음": "HELMET_MISSING",
    "안전모 미착용 가능": "HELMET_MISSING",
    "안전모 착용 불명": "OTHER",
    "안전화 착용": "SAFETY_SHOES_WORN",
    "미끄럼 방지화 미착용": "SAFETY_SHOES_MISSING",
    "미끄럼 방지화 착용": "SAFETY_SHOES_WORN",
    "보호복 미착용": "VEST_MISSING",
    "내화복 미착용": "VEST_MISSING",
    "반사 조끼 없음": "VEST_MISSING",
    "귀마개 미착용": "OTHER",
    "귀마개 착용": "OTHER",
    "귀마개 미착용 (이어폰 착용)": "OTHER",
    "방폭 복장 착용": "OTHER",
    "방폭 도구 미사용": "OTHER",
    "적절 착용": "OTHER",
    "작업복 착용": "OTHER",
    "통풍 의복 미착용": "OTHER",
    "무릎 보호대 미착용": "OTHER",
    "허리 지지대 미착용": "OTHER",
    "직원 보호 없음": "OTHER",
    "보호 덮개 없음": "OTHER",
    "휴식 중": "OTHER",
    "구명복 미착용": "OTHER",
    "적절한 훈련 복장": "OTHER",
    # v10 concise Korean PPE labels.
    "장갑": "GLOVE_WORN",
    "절연장갑": "GLOVE_WORN",
    "니트릴 장갑": "GLOVE_WORN",
    "안전화": "SAFETY_SHOES_WORN",
    "안전모": "HELMET_WORN",
    "안전대": "HARNESS_TIED",
    "고글": "GOGGLES_WORN",
    "안면보호구": "GOGGLES_WORN",
    "레이저 보호 안경": "GOGGLES_WORN",
    "마스크": "MASK_WORN",
    "방진마스크": "MASK_WORN",
    "방독마스크": "MASK_WORN",
    "송기마스크": "MASK_WORN",
    "보호복": "VEST_WORN",
    "방호복": "VEST_WORN",
    "극저온 장갑": "GLOVE_WORN",
    "내열장갑": "GLOVE_WORN",
    "허리보호대": "OTHER",
    "미끄럼방지 신발": "SAFETY_SHOES_WORN",
    "전원 차단": "OTHER",
    "전원 잠금": "OTHER",
    "전원 미차단": "OTHER",
    "LOTO": "OTHER",
    "인터록 활성화": "OTHER",
    "검전기 사용": "OTHER",
    "절연 공구": "OTHER",
})

UNSUPPORTED_FEATURE_ALIASES.setdefault("environmental", {}).update({
    # v10 location/procedure labels. Most are context notes, not risk states.
    "실험실": "OTHER",
    "복도": "OTHER",
    "병실": "OTHER",
    "사무실": "OTHER",
    "급식실": "OTHER",
    "치료실": "OTHER",
    "창고": "OTHER",
    "전기실": "OTHER",
    "화장실": "OTHER",
    "수술실": "OTHER",
    "체육관": "OTHER",
    "수치료실": "OTHER",
    "회의실": "OTHER",
    "교실": "OTHER",
    "방사선실": "OTHER",
    "EMC 시험실": "OTHER",
    "상담실": "OTHER",
    "생활실": "OTHER",
    "진료실": "OTHER",
    "보호시설": "OTHER",
    "이용자 가정": "OTHER",
    "2인 협력": "OTHER",
    "2인 배치": "OTHER",
    "2인 방문": "OTHER",
    "2인 체계": "OTHER",
    "감시원 배치": "OTHER",
    "작업 허가서": "OTHER",
    "비상벨 위치 확인": "OTHER",
    "방어적 자리 배치": "OTHER",
    "위험 이력 공유": "OTHER",
    "문 잠김": "OTHER",
    "신입 직원 단독": "OTHER",
    "단독 순찰": "OTHER",
    "단독 모니터링": "OTHER",
    "단독 담당": "OTHER",
    "연락 불가": "OTHER",
    "야간 단독": "LOW_LIGHT",
    "무전압 확인": "OTHER",
    "LOTO 이행": "OTHER",
    "차단기 차단": "OTHER",
    "전원 차단": "OTHER",
    "전원 차단 확인": "OTHER",
    "가스 측정 및 환기 확인": "OTHER",
    "산소 챔버": "NARROW_SPACE",
    "카트 사용": "OTHER",
    "카트 고정": "OTHER",
    "낮은 발판": "OTHER",
    "지면 작업": "OTHER",
    "경량 자재": "OTHER",
    "unlocked_medicine": "CLUTTERED",
    "child_accessible": "OTHER",
})

UNSUPPORTED_FEATURE_ALIASES.setdefault("accident_types", {}).update({
    "감전": "ELECTRIC_SHOCK",
    "전기 쇼크": "ELECTRIC_SHOCK",
    "전기 화재": "FIRE",
    "과부하 합선": "FIRE",
    "콘센트 과부하 화재": "FIRE",
    "반복 트립으로 인한 화재": "FIRE",
    "전원 불안정으로 인한 전기 사고": "ELECTRIC_SHOCK",
    "화재": "FIRE",
    "화재 확산": "FIRE",
    "연료 화재": "FIRE",
    "화재 잠재": "FIRE",
    "연료통 화재": "FIRE",
    "쓰레기통 화재": "FIRE",
    "지속 누출 시 화재 잠재": "FIRE",
    "화재 초기 대응 실패": "FIRE",
    "인화성 가스 점화": "FIRE",
    "정전기 점화": "FIRE",
    "정전기 점화 가능성 (논란)": "FIRE",
    "정전기 방전으로 인한 연료 증기 점화": "FIRE",
    "접지 불량으로 인한 정전기 점화": "FIRE",
    "스파크 점화": "FIRE",
    "전동 드릴 스파크에 의한 연료 점화": "FIRE",
    "흡착포 자연 발화": "FIRE",
    "화재·폭발": "EXPLOSION",
    "폭발": "EXPLOSION",
    "연료 점화 폭발": "EXPLOSION",
    "연료 하수 계통 침투 화재·폭발": "EXPLOSION",
    "연료 가스 폭발": "EXPLOSION",
    "질식": "CHEMICAL_EXPOSURE",
    "밀폐 공간 질식": "CHEMICAL_EXPOSURE",
    "일산화탄소 중독": "CHEMICAL_EXPOSURE",
    "일산화탄소 축적": "CHEMICAL_EXPOSURE",
    "이산화탄소 과다 축적": "CHEMICAL_EXPOSURE",
    "염소 가스 흡입 중독": "CHEMICAL_EXPOSURE",
    "연료 가스 중독": "CHEMICAL_EXPOSURE",
    "탄화수소 증기 흡입 중독": "CHEMICAL_EXPOSURE",
    "고농도 탄화수소 증기 흡입": "CHEMICAL_EXPOSURE",
    "탄화수소 증기 흡입": "CHEMICAL_EXPOSURE",
    "증기 만성 노출": "CHEMICAL_EXPOSURE",
    "연료 누출 증기 흡입": "CHEMICAL_EXPOSURE",
    "화학 증기 흡입 의식 불명": "CHEMICAL_EXPOSURE",
    "의식 불명": "CHEMICAL_EXPOSURE",
    "농약 중독": "CHEMICAL_EXPOSURE",
    "농약 흡입 중독": "CHEMICAL_EXPOSURE",
    "농약 눈 접촉": "CHEMICAL_EXPOSURE",
    "잔류 농약 피부 흡수": "CHEMICAL_EXPOSURE",
    "피부·눈 접촉 화학 부상": "CHEMICAL_EXPOSURE",
    "토양 오염 2차 노출": "CHEMICAL_EXPOSURE",
    "비료 분진 흡입": "CHEMICAL_EXPOSURE",
    "눈 자극": "CHEMICAL_EXPOSURE",
    "화학 세제 흡입": "CHEMICAL_EXPOSURE",
    "실내 공기질 저하": "CHEMICAL_EXPOSURE",
    "호흡기 불쾌": "CHEMICAL_EXPOSURE",
    "환기 성능 저하": "CHEMICAL_EXPOSURE",
    "간접 흡연": "CHEMICAL_EXPOSURE",
    "만성 신경 독성": "CHEMICAL_EXPOSURE",
    "압사": "CRUSH",
    "압상": "CRUSH",
    "신체 말림": "CRUSH",
    "PTO 회전 말림 사고": "CRUSH",
    "예기치 않은 시동으로 인한 부상": "CRUSH",
    "적재물 붕괴": "COLLAPSE",
    "토사 붕괴": "COLLAPSE",
    "매몰": "COLLAPSE",
    "절단": "CUT",
    "탈곡 날 절단": "CUT",
    "전지가위 절상": "CUT",
    "고압 물 분출 부상": "CUT",
    "고소 추락": "FALL",
    "사다리 추락": "FALL",
    "추락": "FALL",
    "의자 전도 추락": "FALL",
    "계단 전도": "FALL",
    "두부 외상": "FALL",
    "골절": "FALL",
    "미끄럼 전도": "SLIP",
    "전도": "SLIP",
    "전도 부상": "SLIP",
    "과밀 전도": "SLIP",
    "충돌": "COLLISION",
    "농기계 전복": "COLLISION",
    "리어카 전복": "COLLISION",
    "비상구 차단 가능": "COLLISION",
    "화재 시 탈출 불가": "COLLISION",
    "화재 시 대피 유도 실패": "COLLISION",
    "구조 지연": "COLLISION",
    "수용 인원 초과": "COLLISION",
    "과밀로 인한 탈출 지연": "COLLISION",
    "화재 시 압사": "CRUSH",
    "폭행 부상": "COLLISION",
    "직원 안전 위협": "COLLISION",
    "강도 폭행": "COLLISION",
    "직원 신변 위협": "COLLISION",
    "방범 설비 오작동 시 강도 대응 실패": "COLLISION",
    "열사병": "BURN",
    "열탈진": "BURN",
    "요통": "ERGONOMIC",
    "근골격계 부상": "ERGONOMIC",
    "근골격계 질환": "ERGONOMIC",
    "무릎 관절 손상": "ERGONOMIC",
    "소음성 난청": "NOISE",
    "극심한 소음성 난청": "NOISE",
    "순간 청력 손상": "NOISE",
    "소음성 난청 (누적)": "NOISE",
    "청력 손실": "NOISE",
    "이어폰 추가 소음 노출": "NOISE",
    "환경 오염": "CHEMICAL_EXPOSURE",
    "지중 오염": "CHEMICAL_EXPOSURE",
    "연료 누출 미감지 지속": "CHEMICAL_EXPOSURE",
    "연료 유출 미감지": "CHEMICAL_EXPOSURE",
    "탱크 균열 연료 누출": "CHEMICAL_EXPOSURE",
    "소량 연료 점진적 누출": "CHEMICAL_EXPOSURE",
    "익수": "SLIP",
    "두통·현기증": "CHEMICAL_EXPOSURE",
    "화재 감지 실패": "FIRE",
    "소화 실패": "FIRE",
    # v10 social welfare / healthcare / lab wording.
    "화학 흡입": "CHEMICAL_EXPOSURE",
    "화학 노출": "CHEMICAL_EXPOSURE",
    "화학 사고": "CHEMICAL_EXPOSURE",
    "화학 증기 흡입": "CHEMICAL_EXPOSURE",
    "화학 증기 노출": "CHEMICAL_EXPOSURE",
    "약품 흡입": "CHEMICAL_EXPOSURE",
    "피부 자극": "CHEMICAL_EXPOSURE",
    "피부 노출": "CHEMICAL_EXPOSURE",
    "피부 접촉": "CHEMICAL_EXPOSURE",
    "마취 가스 흡입": "CHEMICAL_EXPOSURE",
    "두통": "CHEMICAL_EXPOSURE",
    "발암물질 흡입": "CHEMICAL_EXPOSURE",
    "독성 가스 흡입": "CHEMICAL_EXPOSURE",
    "유해 가스 중독": "CHEMICAL_EXPOSURE",
    "가스 중독": "CHEMICAL_EXPOSURE",
    "끼임": "CRUSH",
    "협착": "CRUSH",
    "회전체 부상": "CRUSH",
    "손가락 부상": "CRUSH",
    "화상": "BURN",
    "아크 화상": "BURN",
    "극저온 화상": "BURN",
    "고압 분출": "CUT",
    "미끄러짐": "SLIP",
    "환자 낙상": "FALL",
    "이용자 낙상": "FALL",
    "낙하": "FALLING_OBJECT",
    "낙하물": "FALLING_OBJECT",
    "실린더 전도": "FALLING_OBJECT",
    "고압 가스 누출": "CHEMICAL_EXPOSURE",
    "인화": "FIRE",
    "폭력": "COLLISION",
    "위협": "COLLISION",
    "갑작스러운 공격": "COLLISION",
    "탈출 불가": "COLLISION",
    "직원 위험": "COLLISION",
    "치료사 부상": "COLLISION",
    "부상": "COLLISION",
    "야간 응급": "ERGONOMIC",
    "야간 단독 위험": "ERGONOMIC",
    "야간 단독 응급": "ERGONOMIC",
    "야간 사고": "ERGONOMIC",
    "응급 대응 미숙": "ERGONOMIC",
    "단독 작업 사고": "ERGONOMIC",
    "자해": "ERGONOMIC",
    "이용자 자해": "ERGONOMIC",
    "응급 상황": "ERGONOMIC",
    "절상": "CUT",
    "교상": "CUT",
    "할큄": "CUT",
    "레이저 눈 손상": "BURN",
    "방사선 피폭": "CHEMICAL_EXPOSURE",
    "산소 과잉": "FIRE",
    "의도치 않은 화학 반응": "CHEMICAL_EXPOSURE",
    "아동 약품 오인 섭취": "CHEMICAL_EXPOSURE",
})

UNSUPPORTED_FEATURE_ALIASES.setdefault("hazardous_agents", {}).update({
    "전기": "ELECTRICITY",
    "전기 과부하": "ELECTRICITY",
    "전선 피복 손상": "ELECTRICITY",
    "잘못된 차단기 조작": "ELECTRICITY",
    "UPS 배터리 노화": "ELECTRICITY",
    "전원 이상": "ELECTRICITY",
    "미차단 전원": "ELECTRICITY",
    "스파크": "FIRE",
    "점화원": "FIRE",
    "점화원(담배)": "FIRE",
    "흡연": "FIRE",
    "자연 발화": "FIRE",
    "화재": "FIRE",
    "인화성 물질": "FIRE",
    "인화성 액체": "FIRE",
    "인화성 가스 축적": "FIRE",
    "가솔린": "FIRE",
    "휘발유": "FIRE",
    "휘발유 증기": "FIRE",
    "휘발유 미세 누출": "FIRE",
    "대량 휘발유 유출": "FIRE",
    "연료 증기": "FIRE",
    "대량 연료 증기": "FIRE",
    "탄화수소 가스": "FIRE",
    "연료 포화 흡착포": "FIRE",
    "유출 휘발유": "FIRE",
    "잔류 연료": "FIRE",
    "연료 이송": "FIRE",
    "배수로 연료 유입": "FIRE",
    "소량 휘발유": "FIRE",
    "탱크 연료 가스": "FIRE",
    "연료 누출": "FIRE",
    "연료 누출 가능성": "FIRE",
    "주유기 오작동": "FIRE",
    "플라스틱 연료통": "FIRE",
    "전동 공구": "ELECTRICITY",
    "정전기": "ELECTRICITY",
    "방범 설비 미비": "OTHER",
    "피로 유발 감시 공백": "OTHER",
    "심야 단독 근무": "OTHER",
    "단독 근무": "OTHER",
    "야간 단독 근무": "OTHER",
    "고소 작업": "OTHER",
    "사다리": "OTHER",
    "불안정 구조물": "OTHER",
    "불안정한 발판": "OTHER",
    "경사지": "OTHER",
    "경사로": "OTHER",
    "수분": "OTHER",
    "수로": "OTHER",
    "야간 시야 불량": "OTHER",
    "불안정 자세": "OTHER",
    "과적 운반도구": "OTHER",
    "시야 차단 운반": "OTHER",
    "중량물": "OTHER",
    "고적재 중량물": "OTHER",
    "관리기 중량": "OTHER",
    "부적절한 취급 자세": "OTHER",
    "부적절한 작업 자세": "OTHER",
    "반복 작업": "OTHER",
    "과밀 집합": "OTHER",
    "계단 과밀": "OTHER",
    "복도 과밀": "OTHER",
    "폭력적 고객": "OTHER",
    "단독 대응": "OTHER",
    "난간 불량": "OTHER",
    "비상구 차단": "OTHER",
    "비상구 통로 차단": "OTHER",
    "화재 감지기 무력화": "OTHER",
    "불량 소화기": "OTHER",
    "유도등 오작동": "OTHER",
    "살충제": "CHEMICAL",
    "제초제": "CHEMICAL",
    "살충제 증기": "TOXIC",
    "훈증제": "TOXIC",
    "잔류 살충제": "CHEMICAL",
    "살충제 잔류": "CHEMICAL",
    "화학약품 증기": "TOXIC",
    "화학약품": "CHEMICAL",
    "혼합 세제 가스": "TOXIC",
    "염소": "TOXIC",
    "산성": "CORROSION",
    "강산 또는 강알칼리 세제": "CORROSION",
    "질산암모늄": "CHEMICAL",
    "요소 분진": "DUST",
    "비료 분진": "DUST",
    "미세먼지": "DUST",
    "오염 필터 미세먼지·곰팡이": "DUST",
    "일산화탄소": "TOXIC",
    "CO": "TOXIC",
    "배기가스 CO": "TOXIC",
    "고농도 CO2": "TOXIC",
    "담배 연기": "TOXIC",
    "벤젠": "TOXIC",
    "토양 오염": "TOXIC",
    "산소 결핍": "TOXIC",
    "회전 동력 전달장치": "OTHER",
    "탈곡 회전날": "OTHER",
    "콤바인 내부 기계": "OTHER",
    "트랙터 동력": "OTHER",
    "날카로운 절단 도구": "OTHER",
    "잔류 수압": "OTHER",
    "노래방 고소음": "NOISE",
    "서버 팬 소음": "NOISE",
    "이어폰 소음": "NOISE",
    "합산 105dB 소음": "NOISE",
    "노래방 소음": "NOISE",
    "장시간 노출": "NOISE",
    "고온 환경": "HEAT_COLD",
    "습도": "OTHER",
    "덕트 부분 차단": "OTHER",
    "환기 불량": "OTHER",
    "젖은 미끄러운 바닥": "OTHER",
    "야간 단독 작업": "OTHER",
    "굴착 불안정 토사": "OTHER",
    "탱크 상부 고소": "OTHER",
    # v10 social welfare / healthcare / lab wording.
    "분전반": "ELECTRICITY",
    "전원 미차단": "ELECTRICITY",
    "대기 전원": "ELECTRICITY",
    "누전": "ELECTRICITY",
    "전선 손상": "ELECTRICITY",
    "동력 배선": "ELECTRICITY",
    "고열 표면": "HEAT_COLD",
    "고온 증기": "HEAT_COLD",
    "액체 질소": "HEAT_COLD",
    "극저온 표면": "HEAT_COLD",
    "소독제": "CHEMICAL",
    "휘발성 유기 용매": "TOXIC",
    "잔류 화학물질": "TOXIC",
    "이소플루란": "TOXIC",
    "마취 가스": "TOXIC",
    "잔류 가스": "TOXIC",
    "고압 가스 실린더": "FIRE",
    "가스 누출": "FIRE",
    "인화성": "FIRE",
    "분무 흡입": "CHEMICAL",
    "약품 분진": "DUST",
    "잔류 회전": "OTHER",
    "원심분리기 로터": "OTHER",
    "회전부": "OTHER",
    "습윤 바닥": "OTHER",
    "습윤 환경": "OTHER",
    "높이": "OTHER",
    "계단": "OTHER",
    "시야 차단": "OTHER",
    "야간 취약": "OTHER",
    "야간 단독": "OTHER",
    "단독 위험": "OTHER",
    "이용자 공격성": "OTHER",
    "공격성 이용자": "OTHER",
    "위기 이용자": "OTHER",
    "섬망 환자": "OTHER",
    "고위험 이용자": "OTHER",
    "중량물 자세": "OTHER",
    "반복 중량 작업": "OTHER",
    "과중량 단독 이송": "OTHER",
    "환자 낙상": "OTHER",
    "중증 환자": "OTHER",
    "날카로운 도구": "OTHER",
    "동물 교상": "BIOLOGICAL",
    "고양이 할큄": "BIOLOGICAL",
    "대형견": "BIOLOGICAL",
    "X선": "RADIATION",
    "방사선": "RADIATION",
    "레이저": "RADIATION",
    "광 방사": "RADIATION",
    "고농도 산소": "FIRE",
    "인화": "FIRE",
    "미확인 혼합 세제": "CHEMICAL",
    "아동 접근 가능 약품": "CHEMICAL",
})

CROSS_FIELD_ALIASES.update({
    ("accident_types", "NOISE"): ("hazardous_agents", "NOISE"),
    ("accident_types", "아크 화상"): ("hazardous_agents", "ARC_FLASH"),
    ("accident_types", "방사선 피폭"): ("hazardous_agents", "RADIATION"),
    ("accident_types", "레이저 눈 손상"): ("hazardous_agents", "RADIATION"),
    ("accident_types", "고압 가스 누출"): ("hazardous_agents", "FIRE"),
    ("accident_types", "산소 과잉"): ("hazardous_agents", "FIRE"),
    ("accident_types", "인화"): ("hazardous_agents", "FIRE"),
    ("environmental", "유기용제"): ("hazardous_agents", "TOXIC"),
    ("environmental", "유기용제_누출"): ("hazardous_agents", "TOXIC"),
    ("environmental", "유기용제_누출_위험"): ("hazardous_agents", "TOXIC"),
    ("environmental", "화학_약품"): ("hazardous_agents", "CHEMICAL"),
    ("environmental", "화학_약품_노출"): ("hazardous_agents", "CHEMICAL"),
    ("environmental", "화학_약품_보관"): ("hazardous_agents", "CHEMICAL"),
    ("environmental", "생물학적_위험"): ("hazardous_agents", "BIOLOGICAL"),
    ("environmental", "동물_교상_위험"): ("hazardous_agents", "BIOLOGICAL"),
    ("environmental", "동물_낙하_위험"): ("accident_types", "FALLING_OBJECT"),
    ("environmental", "컨베이어_벨트"): ("work_contexts", "CONVEYOR_BELT"),
    ("environmental", "프레스_기계"): ("work_contexts", "PRESS_MACHINE"),
    ("environmental", "회전_기계"): ("work_contexts", "MACHINE"),
    ("environmental", "고압_세척기"): ("work_contexts", "HIGH_PRESSURE_WASH"),
    ("environmental", "지게차"): ("work_contexts", "FORKLIFT_OPERATION"),
    ("environmental", "지게차_작업"): ("work_contexts", "FORKLIFT_OPERATION"),
    ("environmental", "하역_도크"): ("work_contexts", "LOADING_DOCK"),
    ("environmental", "창고 실내"): ("work_contexts", "PACKAGE_SORTING"),
    ("environmental", "실내 보관창고"): ("work_contexts", "HIGH_SHELF_WORK"),
    ("environmental", "선반"): ("work_contexts", "HIGH_SHELF_WORK"),
    ("environmental", "과하중"): ("work_contexts", "HEAVY_LIFTING"),
    ("environmental", "과적_팔레트"): ("work_contexts", "HEAVY_LIFTING"),
    ("environmental", "이동식_발판"): ("work_contexts", "LADDER"),
    ("environmental", "차량"): ("work_contexts", "VEHICLE"),
    ("environmental", "야외 농경지"): ("work_contexts", "HARVEST_WORK"),
    ("environmental", "농경지 야외"): ("work_contexts", "HARVEST_WORK"),
    ("environmental", "농경지 작업 현장"): ("work_contexts", "HARVEST_WORK"),
    ("environmental", "농경지"): ("work_contexts", "HARVEST_WORK"),
    ("environmental", "농경지 통로"): ("work_contexts", "HARVEST_WORK"),
    ("environmental", "농경지 관개 시설"): ("work_contexts", "IRRIGATION"),
    ("environmental", "PC방 전기실"): ("work_contexts", "ELECTRICAL_OVERLOAD"),
    ("environmental", "PC방 비상구"): ("work_contexts", "FIRE_EVACUATION"),
    ("environmental", "PC방 서버실"): ("work_contexts", "VENTILATION_POOR"),
    ("environmental", "PC방 공조실"): ("work_contexts", "VENTILATION_POOR"),
    ("environmental", "서버실"): ("work_contexts", "VENTILATION_POOR"),
    ("environmental", "노래방 + 외부 공사 소음"): ("work_contexts", "NOISE_EXPOSURE"),
    ("environmental", "소음"): ("work_contexts", "NOISE_EXPOSURE"),
    ("environmental", "주유소 주유 구역"): ("work_contexts", "FUEL_DISPENSING"),
    ("environmental", "주유소 차량 내외부"): ("work_contexts", "FUEL_DISPENSING"),
    ("environmental", "주유소 바닥"): ("work_contexts", "FUEL_SPILL"),
    ("environmental", "주유소 캐노피"): ("work_contexts", "FUEL_DISPENSING"),
    ("environmental", "주유소 캐노피 근무"): ("work_contexts", "FUEL_DISPENSING"),
    ("environmental", "주유소 이송 작업"): ("work_contexts", "VAPOR_EXPOSURE"),
    ("environmental", "주유소 배수로"): ("work_contexts", "FUEL_SPILL"),
    ("environmental", "주유소 쓰레기통"): ("work_contexts", "FUEL_SPILL"),
    ("environmental", "주유소 임시 보관"): ("work_contexts", "FUEL_SPILL"),
    ("environmental", "지하 탱크 맨홀"): ("work_contexts", "UNDERGROUND_TANK"),
    ("environmental", "지하 탱크 점검구"): ("work_contexts", "UNDERGROUND_TANK"),
    ("environmental", "주유소 지하 탱크"): ("work_contexts", "UNDERGROUND_TANK"),
    ("environmental", "심야 주유소 카운터"): ("work_contexts", "NIGHT_SOLO_WORK"),
    ("environmental", "야간 주유소 점검 구역"): ("work_contexts", "NIGHT_SOLO_WORK"),
    ("environmental", "미끄러운_차체"): ("environmental", "WET_SURFACE"),
    ("environmental", "고온_온수"): ("environmental", "EXTREME_TEMPERATURE"),
    ("environmental", "환기 불량"): ("work_contexts", "VENTILATION_POOR"),
    ("environmental", "폐기물 방치"): ("environmental", "CLUTTERED"),
    ("environmental", "온실 내부 고소"): ("accident_types", "FALL"),
    ("environmental", "온실 내부"): ("work_contexts", "GREENHOUSE_WORK"),
    ("environmental", "밀폐 보일러실"): ("work_contexts", "CONFINED_SPACE"),
    ("environmental", "농막 실내"): ("work_contexts", "HARVEST_WORK"),
    ("environmental", "흡연 허용 노래방 룸"): ("hazardous_agents", "FIRE"),
    ("hazardous_agents", "고소 작업"): ("accident_types", "FALL"),
    ("hazardous_agents", "과밀 집합"): ("accident_types", "COLLISION"),
    ("hazardous_agents", "회전 동력 전달장치"): ("accident_types", "CRUSH"),
    ("hazardous_agents", "관리기 중량"): ("accident_types", "CRUSH"),
    ("hazardous_agents", "경사지"): ("environmental", "UNSTABLE_GROUND"),
    ("hazardous_agents", "탈곡 회전날"): ("accident_types", "CUT"),
    ("hazardous_agents", "콤바인 내부 기계"): ("accident_types", "CRUSH"),
    ("hazardous_agents", "트랙터 동력"): ("accident_types", "CRUSH"),
    ("hazardous_agents", "습도"): ("environmental", "WET_SURFACE"),
    ("hazardous_agents", "불안정 구조물"): ("accident_types", "FALL"),
    ("hazardous_agents", "습기"): ("environmental", "WET_SURFACE"),
    ("hazardous_agents", "날카로운 절단 도구"): ("accident_types", "CUT"),
    ("hazardous_agents", "불완전 연소"): ("hazardous_agents", "TOXIC"),
    ("hazardous_agents", "사다리"): ("work_contexts", "LADDER"),
    ("hazardous_agents", "부적절한 작업 자세"): ("accident_types", "ERGONOMIC"),
    ("hazardous_agents", "반복 작업"): ("accident_types", "ERGONOMIC"),
    ("hazardous_agents", "경사로"): ("accident_types", "FALL"),
    ("hazardous_agents", "과적 운반도구"): ("accident_types", "CRUSH"),
    ("hazardous_agents", "시야 차단 운반"): ("accident_types", "COLLISION"),
    ("hazardous_agents", "불안정 자세"): ("accident_types", "FALL"),
    ("hazardous_agents", "수분"): ("environmental", "WET_SURFACE"),
    ("hazardous_agents", "수로"): ("environmental", "WET_SURFACE"),
    ("hazardous_agents", "야간 시야 불량"): ("environmental", "LOW_LIGHT"),
    ("hazardous_agents", "굴착 불안정 토사"): ("accident_types", "COLLAPSE"),
    ("hazardous_agents", "잔류 수압"): ("work_contexts", "PRESSURE_VESSEL"),
    ("hazardous_agents", "탱크 상부 고소"): ("accident_types", "FALL"),
    ("hazardous_agents", "암모니아 가스"): ("hazardous_agents", "TOXIC"),
    ("hazardous_agents", "중량물"): ("accident_types", "ERGONOMIC"),
    ("hazardous_agents", "부적절한 취급 자세"): ("accident_types", "ERGONOMIC"),
    ("hazardous_agents", "고적재 중량물"): ("accident_types", "FALLING_OBJECT"),
    ("hazardous_agents", "비상구 차단"): ("accident_types", "COLLISION"),
    ("hazardous_agents", "화재 감지기 무력화"): ("hazardous_agents", "FIRE"),
    ("hazardous_agents", "불량 소화기"): ("hazardous_agents", "FIRE"),
    ("hazardous_agents", "유도등 오작동"): ("accident_types", "COLLISION"),
    ("hazardous_agents", "환기 불량"): ("work_contexts", "VENTILATION_POOR"),
    ("hazardous_agents", "덕트 부분 차단"): ("work_contexts", "VENTILATION_POOR"),
    ("hazardous_agents", "젖은 미끄러운 바닥"): ("environmental", "WET_SURFACE"),
    ("hazardous_agents", "야간 단독 작업"): ("work_contexts", "NIGHT_SOLO_WORK"),
    ("hazardous_agents", "야간 단독"): ("work_contexts", "NIGHT_SOLO_WORK"),
    ("hazardous_agents", "단독 위험"): ("work_contexts", "NIGHT_SOLO_WORK"),
    ("hazardous_agents", "야간 취약"): ("environmental", "LOW_LIGHT"),
    ("hazardous_agents", "높이"): ("accident_types", "FALL"),
    ("hazardous_agents", "계단"): ("accident_types", "FALL"),
    ("hazardous_agents", "습윤 바닥"): ("environmental", "WET_SURFACE"),
    ("hazardous_agents", "습윤 환경"): ("environmental", "WET_SURFACE"),
    ("hazardous_agents", "시야 차단"): ("accident_types", "COLLISION"),
    ("hazardous_agents", "잔류 회전"): ("accident_types", "CRUSH"),
    ("hazardous_agents", "원심분리기 로터"): ("accident_types", "CRUSH"),
    ("hazardous_agents", "회전부"): ("accident_types", "CRUSH"),
    ("hazardous_agents", "이용자 공격성"): ("accident_types", "COLLISION"),
    ("hazardous_agents", "공격성 이용자"): ("accident_types", "COLLISION"),
    ("hazardous_agents", "위기 이용자"): ("accident_types", "COLLISION"),
    ("hazardous_agents", "섬망 환자"): ("accident_types", "COLLISION"),
    ("hazardous_agents", "고위험 이용자"): ("accident_types", "COLLISION"),
    ("hazardous_agents", "중량물 자세"): ("accident_types", "ERGONOMIC"),
    ("hazardous_agents", "반복 중량 작업"): ("accident_types", "ERGONOMIC"),
    ("hazardous_agents", "과중량 단독 이송"): ("accident_types", "ERGONOMIC"),
    ("hazardous_agents", "환자 낙상"): ("accident_types", "FALL"),
    ("hazardous_agents", "중증 환자"): ("accident_types", "ERGONOMIC"),
    ("hazardous_agents", "날카로운 도구"): ("accident_types", "CUT"),
    ("hazardous_agents", "동물 교상"): ("accident_types", "CUT"),
    ("hazardous_agents", "고양이 할큄"): ("accident_types", "CUT"),
    ("hazardous_agents", "대형견"): ("accident_types", "CUT"),
    ("hazardous_agents", "불안정한 발판"): ("accident_types", "FALL"),
    ("hazardous_agents", "비상구 통로 차단"): ("accident_types", "COLLISION"),
    ("hazardous_agents", "폭력적 고객"): ("accident_types", "COLLISION"),
    ("hazardous_agents", "단독 대응"): ("work_contexts", "CROWD_MANAGEMENT"),
    ("hazardous_agents", "계단 과밀"): ("accident_types", "SLIP"),
    ("hazardous_agents", "난간 불량"): ("accident_types", "FALL"),
    ("hazardous_agents", "복도 과밀"): ("accident_types", "COLLISION"),
    ("hazardous_agents", "심야 단독 근무"): ("work_contexts", "NIGHT_SOLO_WORK"),
    ("hazardous_agents", "방범 설비 미비"): ("work_contexts", "NIGHT_SOLO_WORK"),
    ("hazardous_agents", "피로 유발 감시 공백"): ("work_contexts", "NIGHT_SOLO_WORK"),
    ("hazardous_agents", "단독 근무"): ("work_contexts", "NIGHT_SOLO_WORK"),
    ("hazardous_agents", "야간 단독 근무"): ("work_contexts", "NIGHT_SOLO_WORK"),
})


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    rows = []
    for line_no, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        row = json.loads(line)
        row["_line_no"] = line_no
        rows.append(row)
    return rows


def normalize_features(features: dict[str, Any]) -> tuple[dict[str, list[str]], list[dict[str, str]]]:
    normalized: dict[str, list[str]] = {field: [] for field in FEATURE_ENUMS}
    notes: list[dict[str, str]] = []
    for field, allowed in FEATURE_ENUMS.items():
        values = features.get(field, [])
        if not isinstance(values, list):
            values = []
        out = normalized[field]
        for value in values:
            cross = CROSS_FIELD_ALIASES.get((field, value))
            if cross:
                target_field, mapped = cross
                if mapped in FEATURE_ENUMS[target_field] and mapped not in normalized[target_field]:
                    normalized[target_field].append(mapped)
                notes.append({"field": field, "from": value, "to": f"{target_field}:{mapped}"})
                continue

            mapped = UNSUPPORTED_FEATURE_ALIASES.get(field, {}).get(value, value)
            if mapped != value:
                notes.append({"field": field, "from": value, "to": mapped})
            mapped_cross = CROSS_FIELD_ALIASES.get((field, mapped))
            if mapped_cross:
                target_field, target_value = mapped_cross
                if (
                    target_value in FEATURE_ENUMS[target_field]
                    and target_value not in normalized[target_field]
                ):
                    normalized[target_field].append(target_value)
                notes.append({
                    "field": field,
                    "from": mapped,
                    "to": f"{target_field}:{target_value}",
                })
                continue
            if mapped in allowed and mapped not in out:
                out.append(mapped)
            elif mapped not in allowed:
                notes.append({"field": field, "from": value, "to": "", "error": "unsupported"})
    return normalized, notes


def apply_case_work_context_hint(
    features: dict[str, list[str]],
    case_work_context: str | None,
) -> None:
    """Preserve explicit synthetic case context when faceted codes are too broad."""
    mapped = map_case_work_context(case_work_context)
    if not mapped:
        return
    contexts = features.setdefault("work_contexts", [])
    if mapped not in contexts:
        contexts.append(mapped)
    if len(contexts) > 1 and "GENERAL_WORKPLACE" in contexts:
        contexts[:] = [code for code in contexts if code != "GENERAL_WORKPLACE"]


def unique(values: list[str]) -> list[str]:
    return list(dict.fromkeys(v for v in values if v))


def exposure_for_penalty_candidates(candidates: list[dict[str, Any]], *, direct_allowed: bool) -> str:
    if direct_allowed and any(candidate.get("exposure_type") == "direct_candidate" for candidate in candidates):
        return "DIRECT"
    if candidates:
        return "CONDITIONAL"
    return "NONE"


def evaluate_case(
    db,
    row: dict[str, Any],
    *,
    top_n: int,
    min_matched_dims: int,
    sr_limit: int,
    ci_limit: int,
    allow_context_only_inference: bool,
    penalty_sr_scope: str,
    min_visual_score: float,
    min_agent_only_visual_score: float,
    use_declared_industry: bool,
) -> dict[str, Any]:
    expected = _normalized_expected_behavior(row)
    features, normalization_notes = normalize_features(row.get("expected_features", {}))
    row_work_context = _row_work_context(row)
    row_description = _row_description(row)
    apply_case_work_context_hint(features, row_work_context)
    infer_features_from_row(row, features, normalization_notes)

    canonical_input = {
        "accident_types": features["accident_types"],
        "hazardous_agents": features["hazardous_agents"],
        "work_contexts": features["work_contexts"],
        "unknown_codes": [n["from"] for n in normalization_notes if n.get("error")],
        "forced_fit_notes": [],
    }
    canonical = hazard_rule_engine.apply_rules(
        canonical_input,
        db,
        allow_context_only_inference=allow_context_only_inference,
    )
    industry_context = infer_industry_context(
        work_contexts=canonical["work_contexts"],
        text=" ".join(list(row.get("visual_cues") or []) + [row_description]),
        declared=row.get("industry_context") if use_declared_industry else None,
    )

    visual_cues = (
        list(row.get("visual_cues") or [])
        + list(row.get("uncertain_cues") or [])
        + [row_description]
    )

    matches = she_matcher.match_she(
        db,
        canonical["accident_types"],
        canonical["hazardous_agents"],
        canonical["work_contexts"],
        ppe_states=features["ppe_states"],
        environmental=features["environmental"],
        visual_cues=visual_cues,
        industry_contexts=industry_context.active_industries,
        top_n=top_n,
        min_matched_dims=min_matched_dims,
        min_visual_score=min_visual_score,
        min_agent_only_visual_score=min_agent_only_visual_score,
    )
    she_dicts = [m.to_dict() for m in matches]
    observable_violation_signal = she_matcher.has_observable_violation_signal(
        accident_types=features["accident_types"],
        hazardous_agents=features["hazardous_agents"],
        work_contexts=features["work_contexts"],
        ppe_states=features["ppe_states"],
        environmental=features["environmental"],
        visual_cues=visual_cues,
    )
    confirmed_matches = [
        m for m in matches
        if observable_violation_signal and m.match_status == "confirmed"
    ]
    confirmation_candidate_matches = [
        m for m in matches
        if observable_violation_signal
        and m.match_status in {"candidate", "review_candidate"}
    ]
    actionable_matches = [
        m for m in matches
        if observable_violation_signal
        and m.match_status in she_matcher.ACTIONABLE_MATCH_STATUSES
    ]
    she_sr_ids = unique(sr_id for m in actionable_matches for sr_id in m.applies_sr_ids)
    direct_she_sr_ids = unique(
        sr_id
        for m in matches
        if she_matcher.is_direct_penalty_match(m)
        for sr_id in m.applies_sr_ids
    )

    sr_results = []
    if actionable_matches or observable_violation_signal:
        sr_results = hazard_rule_engine.query_sr_for_facets(
            db,
            canonical["accident_types"],
            canonical["hazardous_agents"],
            canonical["work_contexts"],
            limit=sr_limit,
            industry_contexts=industry_context.active_industries,
        )
    facet_sr_ids = [sr["identifier"] for sr in sr_results]
    sr_ids = unique(she_sr_ids + facet_sr_ids)

    guides = []
    for m in matches:
        guides.extend(m.source_guides)
    try:
        guide_rows = hazard_rule_engine.get_guides_from_srs(
            db,
            sr_ids,
            limit=10,
            industry_contexts=industry_context.active_industries,
        )
        guides.extend(g.get("guide_code") or g.get("identifier") or "" for g in guide_rows)
    except Exception:
        guide_rows = []
    guides = unique(guides)

    ci_rows = hazard_rule_engine.get_checklist_from_srs(db, sr_ids, limit=ci_limit)
    ci_ids = [ci["identifier"] for ci in ci_rows]

    penalty_sr_ids = she_sr_ids if penalty_sr_scope == "she" else sr_ids
    penalty_candidates = hazard_rule_engine.get_penalty_candidates_for_srs(
        penalty_sr_ids,
        direct_sr_ids=direct_she_sr_ids,
        limit=200,
    )
    penalty_rule_ids = unique([
        candidate["penalty_rule_id"]
        for candidate in penalty_candidates
        if candidate.get("penalty_rule_id")
    ])
    direct_allowed = (
        row.get("case_type") == "positive"
        and not expected.get("needs_clarification")
    )
    actual_penalty_exposure = exposure_for_penalty_candidates(
        penalty_candidates,
        direct_allowed=direct_allowed,
    )
    if confirmed_matches and sr_ids:
        finding_status = "suspected"
    elif actionable_matches and sr_ids:
        finding_status = "needs_clarification"
    elif sr_ids:
        finding_status = "suspected"
    else:
        finding_status = "not_determined"
    penalty_paths = hazard_rule_engine.build_penalty_paths(
        penalty_candidates,
        finding_status=finding_status,
    )
    penalty_path_types = {path["path_type"] for path in penalty_paths}

    actual = {
        "should_match_she": bool(actionable_matches),
        "has_confirmed_she": bool(confirmed_matches),
        "has_actionable_she": bool(actionable_matches),
        "has_confirmation_candidate": bool(confirmation_candidate_matches),
        "has_review_candidate": any(m.match_status == "review_candidate" for m in confirmation_candidate_matches),
        "has_she_candidate": bool(matches),
        "observable_violation_signal": observable_violation_signal,
        "should_recommend_sr": bool(sr_ids),
        "penalty_exposure": actual_penalty_exposure,
        "has_general_incident_path": "general_incident" in penalty_path_types,
        "has_death_path": "death" in penalty_path_types,
        "has_serious_accident_path": "serious_accident" in penalty_path_types,
        "death_path_is_external_fact_required": any(
            path["path_type"] == "death" and path["notice_level"] == "external_fact_required"
            for path in penalty_paths
        ),
        "serious_path_is_external_fact_required": any(
            path["path_type"] == "serious_accident" and path["notice_level"] == "external_fact_required"
            for path in penalty_paths
        ),
        "has_guide": bool(guides),
        "has_checklist": bool(ci_ids),
    }

    return {
        "case_id": row["case_id"],
        "case_type": row["case_type"],
        "industry_context": row["industry_context"],
        "work_context": row_work_context,
        "expected": {
            "should_match_she": expected["should_match_she"],
            "should_recommend_sr": expected["should_recommend_sr"],
            "penalty_exposure": expected["penalty_exposure"],
            "preferred_action_source": expected["preferred_action_source"],
            "needs_clarification": expected["needs_clarification"],
        },
        "actual": actual,
        "normalized_features": features,
        "canonical": canonical,
        "industry_context": industry_context.to_dict(),
        "normalization_notes": normalization_notes,
        "she_matches": she_dicts,
        "sr_ids": sr_ids,
        "she_sr_ids": she_sr_ids,
        "direct_she_sr_ids": direct_she_sr_ids,
        "facet_sr_ids": facet_sr_ids,
        "guide_ids": guides,
        "ci_ids": ci_ids,
        "penalty_rule_ids": penalty_rule_ids,
        "penalty_candidates": penalty_candidates,
        "penalty_paths": penalty_paths,
        "direct_penalty_allowed": direct_allowed,
        "penalty_sr_scope": penalty_sr_scope,
        "penalty_sr_ids": penalty_sr_ids,
        "primary_risk": row.get("expected_primary_risk", ""),
        "corrective_direction": row.get("expected_corrective_direction", ""),
        "false_positive_risk": row.get("false_positive_risk", ""),
    }


def pct(numerator: int, denominator: int) -> str:
    if denominator == 0:
        return "0.0%"
    return f"{numerator / denominator:.1%}"


def _expected_confirmed_risk(case: dict[str, Any]) -> bool:
    expected = case["expected"]
    return (
        case["case_type"] == "positive"
        and expected["should_match_she"]
        and not expected.get("needs_clarification")
    )


def _expected_clarification_candidate(case: dict[str, Any]) -> bool:
    expected = case["expected"]
    return (
        expected.get("needs_clarification", False)
        or case["case_type"] == "ambiguous"
    )


def _expected_normal_suppression(case: dict[str, Any]) -> bool:
    expected = case["expected"]
    return (
        case["case_type"] == "negative"
        and not expected.get("needs_clarification", False)
    )


def build_summary(per_case: list[dict[str, Any]]) -> dict[str, Any]:
    total = len(per_case)
    by_type = Counter(case["case_type"] for case in per_case)
    she_confusion = Counter(
        (case["expected"]["should_match_she"], case["actual"]["should_match_she"])
        for case in per_case
    )
    sr_confusion = Counter(
        (case["expected"]["should_recommend_sr"], case["actual"]["should_recommend_sr"])
        for case in per_case
    )
    confirmed_she_confusion = Counter(
        (case["expected"]["should_match_she"], case["actual"].get("has_confirmed_she", False))
        for case in per_case
    )
    penalty_confusion = Counter(
        (case["expected"]["penalty_exposure"], case["actual"]["penalty_exposure"])
        for case in per_case
    )
    penalty_path_counts = Counter(
        path.get("path_type", "unknown")
        for case in per_case
        for path in case.get("penalty_paths", [])
    )
    she_status_counts = Counter(
        match.get("match_status", "unknown")
        for case in per_case
        for match in case.get("she_matches", [])
    )

    expected_she_true = sum(1 for c in per_case if c["expected"]["should_match_she"])
    expected_she_false = total - expected_she_true
    she_tp = she_confusion[(True, True)]
    she_fn = she_confusion[(True, False)]
    she_fp = she_confusion[(False, True)]
    she_tn = she_confusion[(False, False)]

    confirmed_expected = [c for c in per_case if _expected_confirmed_risk(c)]
    clarification_expected = [c for c in per_case if _expected_clarification_candidate(c)]
    normal_expected = [c for c in per_case if _expected_normal_suppression(c)]

    confirmed_tp = sum(1 for c in confirmed_expected if c["actual"].get("has_confirmed_she"))
    confirmed_fn = len(confirmed_expected) - confirmed_tp
    confirmed_fp = sum(
        1
        for c in per_case
        if not _expected_confirmed_risk(c)
        and c["actual"].get("has_confirmed_she")
    )
    confirmed_downgraded_to_candidate = sum(
        1
        for c in confirmed_expected
        if not c["actual"].get("has_confirmed_she")
        and c["actual"].get("has_confirmation_candidate")
    )

    clarification_captured = sum(
        1
        for c in clarification_expected
        if c["actual"].get("has_confirmation_candidate")
        or c["actual"].get("has_confirmed_she")
    )
    clarification_as_candidate = sum(
        1
        for c in clarification_expected
        if c["actual"].get("has_confirmation_candidate")
        and not c["actual"].get("has_confirmed_she")
    )
    clarification_over_promoted = sum(
        1
        for c in clarification_expected
        if c["actual"].get("has_confirmed_she")
    )
    clarification_missed = len(clarification_expected) - clarification_captured

    normal_suppressed = sum(
        1
        for c in normal_expected
        if not c["actual"].get("has_confirmed_she")
        and not c["actual"].get("has_confirmation_candidate")
        and not c["actual"].get("should_match_she")
    )
    normal_confirmed_fp = sum(
        1 for c in normal_expected if c["actual"].get("has_confirmed_she")
    )
    normal_candidate_fp = sum(
        1
        for c in normal_expected
        if c["actual"].get("has_confirmation_candidate")
        and not c["actual"].get("has_confirmed_she")
    )

    return {
        "total": total,
        "by_case_type": dict(by_type),
        "she_confusion": {f"expected_{k[0]}__actual_{k[1]}": v for k, v in she_confusion.items()},
        "confirmed_she_confusion": {f"expected_{k[0]}__actual_{k[1]}": v for k, v in confirmed_she_confusion.items()},
        "she_status_counts": dict(she_status_counts),
        "sr_confusion": {f"expected_{k[0]}__actual_{k[1]}": v for k, v in sr_confusion.items()},
        "penalty_confusion": {f"expected_{k[0]}__actual_{k[1]}": v for k, v in penalty_confusion.items()},
        "penalty_path_counts": dict(penalty_path_counts),
        "has_general_incident_path_count": sum(
            1 for c in per_case if c["actual"].get("has_general_incident_path")
        ),
        "has_death_path_count": sum(
            1 for c in per_case if c["actual"].get("has_death_path")
        ),
        "has_serious_accident_path_count": sum(
            1 for c in per_case if c["actual"].get("has_serious_accident_path")
        ),
        "death_external_fact_required_count": sum(
            1 for c in per_case if c["actual"].get("death_path_is_external_fact_required")
        ),
        "serious_external_fact_required_count": sum(
            1 for c in per_case if c["actual"].get("serious_path_is_external_fact_required")
        ),
        "she_positive_recall": pct(she_tp, expected_she_true),
        "she_false_negative_count": she_fn,
        "she_false_positive_count": she_fp,
        "she_negative_specificity": pct(she_tn, expected_she_false),
        "separated_metrics": {
            "confirmed_risk": {
                "expected_count": len(confirmed_expected),
                "true_positive": confirmed_tp,
                "false_negative": confirmed_fn,
                "false_positive": confirmed_fp,
                "downgraded_to_confirmation_candidate": confirmed_downgraded_to_candidate,
                "recall": pct(confirmed_tp, len(confirmed_expected)),
                "precision": pct(confirmed_tp, confirmed_tp + confirmed_fp),
            },
            "clarification_candidate": {
                "expected_count": len(clarification_expected),
                "captured": clarification_captured,
                "as_candidate": clarification_as_candidate,
                "over_promoted_to_confirmed": clarification_over_promoted,
                "missed": clarification_missed,
                "capture_rate": pct(clarification_captured, len(clarification_expected)),
                "candidate_rate": pct(clarification_as_candidate, len(clarification_expected)),
                "over_promotion_rate": pct(clarification_over_promoted, len(clarification_expected)),
            },
            "normal_suppression": {
                "expected_count": len(normal_expected),
                "suppressed": normal_suppressed,
                "confirmed_false_positive": normal_confirmed_fp,
                "candidate_false_positive": normal_candidate_fp,
                "suppression_rate": pct(normal_suppressed, len(normal_expected)),
            },
        },
        "she_candidate_count": sum(1 for c in per_case if c["actual"].get("has_she_candidate")),
        "she_candidates_suppressed_by_signal_gate": sum(
            1
            for c in per_case
            if c["actual"].get("has_she_candidate")
            and not c["actual"].get("observable_violation_signal")
        ),
        "industry_confirmation_count": sum(
            1
            for c in per_case
            if c.get("industry_context", {}).get("needs_confirmation")
        ),
        "normalization_note_count": sum(len(c["normalization_notes"]) for c in per_case),
        "cases_with_normalization": [
            c["case_id"] for c in per_case if c["normalization_notes"]
        ],
    }


def write_markdown_report(path: Path, summary: dict[str, Any], per_case: list[dict[str, Any]]) -> None:
    false_negatives = [
        c for c in per_case
        if c["expected"]["should_match_she"] and not c["actual"]["should_match_she"]
    ]
    false_positives = [
        c for c in per_case
        if not c["expected"]["should_match_she"] and c["actual"]["should_match_she"]
    ]
    penalty_mismatch = [
        c for c in per_case
        if c["expected"]["penalty_exposure"] != c["actual"]["penalty_exposure"]
    ]

    lines = [
        "# 합성 관찰사실 평가 리포트",
        "",
        f"- 생성시각(UTC): {datetime.now(timezone.utc).isoformat(timespec='seconds')}",
        f"- 총 케이스: {summary['total']}",
        f"- 케이스 유형: {summary['by_case_type']}",
        f"- SHE positive recall: {summary['she_positive_recall']}",
        f"- SHE false negative: {summary['she_false_negative_count']}",
        f"- SHE false positive: {summary['she_false_positive_count']}",
        f"- SHE negative specificity: {summary['she_negative_specificity']}",
        f"- SHE candidate count: {summary['she_candidate_count']}",
        f"- Signal gate suppressed candidates: {summary['she_candidates_suppressed_by_signal_gate']}",
        f"- Industry confirmation needed: {summary['industry_confirmation_count']}",
        f"- 정규화 발생 케이스: {len(summary['cases_with_normalization'])}개",
        "",
        "## 분리 평가지표",
        "",
        "```text",
        json.dumps(summary["separated_metrics"], ensure_ascii=False, indent=2),
        "```",
        "",
        "## SHE 혼동 행렬",
        "",
        "```text",
        json.dumps(summary["she_confusion"], ensure_ascii=False, indent=2),
        "```",
        "",
        "## SHE confirmed 혼동 행렬",
        "",
        "```text",
        json.dumps(summary["confirmed_she_confusion"], ensure_ascii=False, indent=2),
        "```",
        "",
        "## SHE match_status",
        "",
        "```text",
        json.dumps(summary["she_status_counts"], ensure_ascii=False, indent=2),
        "```",
        "",
        "## SR 추천 혼동 행렬",
        "",
        "```text",
        json.dumps(summary["sr_confusion"], ensure_ascii=False, indent=2),
        "```",
        "",
        "## 벌칙 노출 혼동 행렬",
        "",
        "```text",
        json.dumps(summary["penalty_confusion"], ensure_ascii=False, indent=2),
        "```",
        "",
        "## PenaltyPath 3경로 지표",
        "",
        "```text",
        json.dumps({
            "path_counts": summary["penalty_path_counts"],
            "has_general_incident_path_count": summary["has_general_incident_path_count"],
            "has_death_path_count": summary["has_death_path_count"],
            "has_serious_accident_path_count": summary["has_serious_accident_path_count"],
            "death_external_fact_required_count": summary["death_external_fact_required_count"],
            "serious_external_fact_required_count": summary["serious_external_fact_required_count"],
        }, ensure_ascii=False, indent=2),
        "```",
        "",
        "## 정규화 메모",
        "",
    ]
    if summary["cases_with_normalization"]:
        for case in per_case:
            if case["normalization_notes"]:
                lines.append(f"- {case['case_id']}: {case['normalization_notes']}")
    else:
        lines.append("- 없음")

    lines.extend(["", "## SHE False Negative 샘플", ""])
    for case in false_negatives[:20]:
        lines.append(
            f"- {case['case_id']} ({case['work_context']}): {case['primary_risk']} "
            f"/ features={case['normalized_features']}"
        )

    lines.extend(["", "## SHE False Positive 샘플", ""])
    for case in false_positives[:20]:
        top = [
            {
                "she_id": m["she_id"],
                "score": round(m["match_score"], 3),
                "dims": m["matched_dims"],
                "status": m.get("match_status"),
                "sr": m["applies_sr_ids"][:3],
            }
            for m in case["she_matches"][:3]
        ]
        lines.append(
            f"- {case['case_id']} ({case['case_type']}/{case['work_context']}): "
            f"{case['false_positive_risk']} / top={top}"
        )

    lines.extend(["", "## 벌칙 노출 불일치 샘플", ""])
    for case in penalty_mismatch[:20]:
        lines.append(
            f"- {case['case_id']}: expected={case['expected']['penalty_exposure']}, "
            f"actual={case['actual']['penalty_exposure']}, sr_count={len(case['sr_ids'])}, "
            f"penalty_rule_count={len(case['penalty_rule_ids'])}"
        )

    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_csv(path: Path, per_case: list[dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=[
                "case_id", "case_type", "industry_context", "work_context",
                "expected_she", "actual_she", "expected_sr", "actual_sr",
                "expected_penalty", "actual_penalty", "actual_she_candidate",
                "actual_she_confirmed", "top_she_status",
                "has_confirmation_candidate", "has_review_candidate",
                "observable_violation_signal", "primary_industry",
                "inferred_industries", "industry_needs_confirmation",
                "top_she_industry_alignment", "she_count", "sr_count",
                "guide_count", "ci_count", "penalty_rule_count",
                "has_general_incident_path", "has_death_path", "has_serious_accident_path",
                "death_external_fact_required", "serious_external_fact_required",
                "top_she",
                "normalization_notes",
            ],
        )
        writer.writeheader()
        for case in per_case:
            writer.writerow({
                "case_id": case["case_id"],
                "case_type": case["case_type"],
                "industry_context": case["industry_context"],
                "work_context": case["work_context"],
                "expected_she": case["expected"]["should_match_she"],
                "actual_she": case["actual"]["should_match_she"],
                "expected_sr": case["expected"]["should_recommend_sr"],
                "actual_sr": case["actual"]["should_recommend_sr"],
                "expected_penalty": case["expected"]["penalty_exposure"],
                "actual_penalty": case["actual"]["penalty_exposure"],
                "actual_she_candidate": case["actual"].get("has_she_candidate", False),
                "actual_she_confirmed": case["actual"].get("has_confirmed_she", False),
                "has_confirmation_candidate": case["actual"].get("has_confirmation_candidate", False),
                "has_review_candidate": case["actual"].get("has_review_candidate", False),
                "top_she_status": case["she_matches"][0].get("match_status", "") if case["she_matches"] else "",
                "observable_violation_signal": case["actual"].get("observable_violation_signal", False),
                "primary_industry": case.get("industry_context", {}).get("primary_industry", ""),
                "inferred_industries": json.dumps(case.get("industry_context", {}).get("inferred_industries", []), ensure_ascii=False),
                "industry_needs_confirmation": case.get("industry_context", {}).get("needs_confirmation", False),
                "top_she_industry_alignment": case["she_matches"][0].get("industry_alignment", "") if case["she_matches"] else "",
                "she_count": len(case["she_matches"]),
                "sr_count": len(case["sr_ids"]),
                "guide_count": len(case["guide_ids"]),
                "ci_count": len(case["ci_ids"]),
                "penalty_rule_count": len(case["penalty_rule_ids"]),
                "has_general_incident_path": case["actual"].get("has_general_incident_path", False),
                "has_death_path": case["actual"].get("has_death_path", False),
                "has_serious_accident_path": case["actual"].get("has_serious_accident_path", False),
                "death_external_fact_required": case["actual"].get("death_path_is_external_fact_required", False),
                "serious_external_fact_required": case["actual"].get("serious_path_is_external_fact_required", False),
                "top_she": case["she_matches"][0]["she_id"] if case["she_matches"] else "",
                "normalization_notes": json.dumps(case["normalization_notes"], ensure_ascii=False),
            })


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--input",
        type=Path,
        default=PROJECT_ROOT / "pictures-json" / "synthetic_observations_v1.jsonl",
        help="합성 관찰사실 JSONL 경로",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=PROJECT_ROOT / "pictures-json" / "reports",
        help="평가 리포트 출력 디렉터리",
    )
    parser.add_argument("--top-n", type=int, default=5)
    parser.add_argument("--min-matched-dims", type=int, default=2)
    parser.add_argument("--sr-limit", type=int, default=50)
    parser.add_argument("--ci-limit", type=int, default=15)
    parser.add_argument(
        "--min-visual-score",
        type=float,
        default=0.0,
        help="사진 시각 단서와 SHE visual_triggers 간 최소 유사도. 0이면 비활성화한다.",
    )
    parser.add_argument(
        "--min-agent-only-visual-score",
        type=float,
        default=0.15,
        help="work_context+hazardous_agent만 맞고 accident_type이 없는 SHE 후보에 요구할 최소 시각 유사도.",
    )
    parser.add_argument(
        "--penalty-sr-scope",
        choices=["all", "she"],
        default="all",
        help="벌칙 후보를 넓은 전체 SR에서 찾을지, SHE가 직접 매칭한 SR에서만 찾을지 선택한다.",
    )
    parser.add_argument(
        "--use-declared-industry",
        action="store_true",
        help="Synthetic row의 industry_context를 사용자가 직접 입력한 업종으로 간주한다.",
    )
    parser.add_argument(
        "--no-context-only-inference",
        action="store_true",
        help="Deprecated: 기본값이 이미 off다. 호환성을 위해 남겨둔다.",
    )
    parser.add_argument(
        "--allow-context-only-inference",
        action="store_true",
        help="작업맥락만으로 사고유형/유해인자를 추가하는 교차 추론을 평가에서만 켠다.",
    )
    parser.add_argument(
        "--report-prefix",
        default="synthetic_observations_baseline",
        help="출력 리포트 파일명 prefix",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    rows = load_jsonl(args.input)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    allow_context_only = args.allow_context_only_inference and not args.no_context_only_inference

    db = SessionLocal()
    try:
        per_case = [
            evaluate_case(
                db,
                row,
                top_n=args.top_n,
                min_matched_dims=args.min_matched_dims,
                sr_limit=args.sr_limit,
                ci_limit=args.ci_limit,
                allow_context_only_inference=allow_context_only,
                penalty_sr_scope=args.penalty_sr_scope,
                min_visual_score=args.min_visual_score,
                min_agent_only_visual_score=args.min_agent_only_visual_score,
                use_declared_industry=args.use_declared_industry,
            )
            for row in rows
        ]
    finally:
        db.close()

    summary = build_summary(per_case)
    report = {
        "input": str(args.input),
        "created_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "settings": {
            "top_n": args.top_n,
            "min_matched_dims": args.min_matched_dims,
            "sr_limit": args.sr_limit,
            "ci_limit": args.ci_limit,
            "min_visual_score": args.min_visual_score,
            "min_agent_only_visual_score": args.min_agent_only_visual_score,
            "allow_context_only_inference": allow_context_only,
            "penalty_sr_scope": args.penalty_sr_scope,
            "use_declared_industry": args.use_declared_industry,
        },
        "summary": summary,
        "cases": per_case,
    }

    json_path = args.output_dir / f"{args.report_prefix}_report.json"
    md_path = args.output_dir / f"{args.report_prefix}_report.md"
    csv_path = args.output_dir / f"{args.report_prefix}_cases.csv"
    json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    write_markdown_report(md_path, summary, per_case)
    write_csv(csv_path, per_case)

    print("=== Synthetic Observation Baseline ===")
    print(f"input: {args.input}")
    print(f"cases: {summary['total']} {summary['by_case_type']}")
    print(f"SHE recall: {summary['she_positive_recall']}")
    print(f"SHE false negative: {summary['she_false_negative_count']}")
    print(f"SHE false positive: {summary['she_false_positive_count']}")
    print(f"SHE negative specificity: {summary['she_negative_specificity']}")
    print(f"SHE candidate count: {summary['she_candidate_count']}")
    print(f"Signal gate suppressed candidates: {summary['she_candidates_suppressed_by_signal_gate']}")
    print(f"Separated metrics: {json.dumps(summary['separated_metrics'], ensure_ascii=False)}")
    print(f"SHE status counts: {summary['she_status_counts']}")
    print(f"Industry confirmation needed: {summary['industry_confirmation_count']}")
    print(f"normalization cases: {len(summary['cases_with_normalization'])}")
    print(f"wrote: {json_path}")
    print(f"wrote: {md_path}")
    print(f"wrote: {csv_path}")


if __name__ == "__main__":
    main()
