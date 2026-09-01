"""
auth.py: 인증 및 요금제 로직 (Redis 기반 카운팅)
"""
import hashlib
import logging
import os

from fastapi import HTTPException
from sqlalchemy.exc import IntegrityError

from db import SessionLocal
from models import User, ApiKey, Plan

logger = logging.getLogger("ytmoodapi.auth")

REDIS_HOST = os.getenv("REDIS_HOST", "localhost")
REDIS_PORT = int(os.getenv("REDIS_PORT", 6379))

# Redis is optional: the client is constructed lazily-connecting, so an
# unreachable server does not stop the app from booting. If the package or the
# constructor itself fails we simply run without usage counting.
try:
    import redis

    redis_client = redis.Redis(host=REDIS_HOST, port=REDIS_PORT, decode_responses=True)
except Exception:
    logger.warning("Redis client unavailable; usage limiting disabled", exc_info=True)
    redis_client = None

DEFAULT_PLAN_NAME = "Free"


def _get_or_create_plan(db, name: str) -> Plan:
    plan = db.query(Plan).filter_by(name=name).first()
    if plan:
        return plan
    plan = Plan(name=name)
    db.add(plan)
    try:
        db.commit()
    except IntegrityError:
        # another worker seeded it first
        db.rollback()
        plan = db.query(Plan).filter_by(name=name).first()
    return plan


def _provision(db, api_key: str) -> str:
    """Register an unknown API key under the Free plan and return the plan name."""
    plan = _get_or_create_plan(db, DEFAULT_PLAN_NAME)
    username = "auto_" + hashlib.sha256(api_key.encode()).hexdigest()[:32]
    user = User(username=username, plan_id=plan.id)
    db.add(user)
    db.flush()
    db.add(ApiKey(key=api_key, user_id=user.id))
    try:
        db.commit()
    except IntegrityError:
        # concurrent request registered the same key; theirs wins
        db.rollback()
    return plan.name


# DB에서 api_key로 요금제 이름 반환 (없는 키는 Free 플랜으로 자동 등록)
def get_plan(api_key: str) -> str:
    db = SessionLocal()
    try:
        api_key_obj = db.query(ApiKey).filter_by(key=api_key).first()
        if api_key_obj is None:
            return _provision(db, api_key)
        if api_key_obj.user and api_key_obj.user.plan:
            return api_key_obj.user.plan.name
        return DEFAULT_PLAN_NAME
    finally:
        db.close()


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
    limits = PLAN_LIMITS.get(plan_name)
    if limits is None:
        raise HTTPException(status_code=403, detail="지원하지 않는 플랜")
    if redis_client is None:
        return
    key = f"usage:{api_key}:{plan_name}"
    try:
        count = redis_client.incr(key)
        if count == 1:
            redis_client.expire(key, limits["period"])
    except Exception:
        # Redis down: serve the request rather than failing it
        logger.warning("Redis unreachable; skipping usage check", exc_info=True)
        return
    if int(count) > limits["limit"]:
        raise HTTPException(status_code=429, detail=f"{plan_name} 플랜 사용량 초과")
