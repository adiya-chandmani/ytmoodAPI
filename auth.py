"""
auth.py: 인증 및 요금제 로직 (Redis 기반 카운팅)
"""
from fastapi import HTTPException
import os
import redis
from db import SessionLocal
from models import User, ApiKey, Plan

REDIS_HOST = os.getenv("REDIS_HOST", "localhost")
REDIS_PORT = int(os.getenv("REDIS_PORT", 6379))
redis_client = redis.Redis(host=REDIS_HOST, port=REDIS_PORT, decode_responses=True)

# DB에서 api_key로 요금제 이름 반환
def get_plan(api_key: str) -> str:
    db = SessionLocal()
    api_key_obj = db.query(ApiKey).filter_by(key=api_key).first()
    if not api_key_obj or not api_key_obj.user:
        db.close()
        raise HTTPException(status_code=401, detail="유효하지 않은 API 키")
    user = api_key_obj.user
    plan = db.query(Plan).filter_by(id=user.plan_id).first()
    db.close()
    if not plan:
        raise HTTPException(status_code=403, detail="플랜 정보 없음")
    return plan.name

# DB에서 요금제 정보로 Redis 카운팅
# (요금제별 limit/period는 하드코딩 또는 Plan 테이블 확장 가능)
PLAN_LIMITS = {
    "Free": {"limit": 100, "period": 86400},
    "Pro": {"limit": 30000, "period": 2592000},
    "Business": {"limit": 100000, "period": 2592000},
    "Admin": {"limit": 1000000, "period": 2592000}
}

def check_usage(api_key: str):
    plan_name = get_plan(api_key)
    if plan_name not in PLAN_LIMITS:
        raise HTTPException(status_code=403, detail="지원하지 않는 플랜")
    period = PLAN_LIMITS[plan_name]["period"]
    limit = PLAN_LIMITS[plan_name]["limit"]
    key = f"usage:{api_key}:{plan_name}"
    count = redis_client.get(key)
    if count is None:
        redis_client.set(key, 1, ex=period)
        count = 1
    else:
        count = redis_client.incr(key)
    if int(count) > limit:
        raise HTTPException(status_code=429, detail=f"{plan_name} 플랜 사용량 초과") 