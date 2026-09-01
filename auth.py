"""
auth.py: 인증 및 요금제 로직 (Redis 기반 카운팅)
"""
import hashlib
import logging
import os
import secrets
import time
from typing import Optional

from fastapi import Header, HTTPException
from sqlalchemy.exc import IntegrityError

from db import SessionLocal
from models import ApiKey, Plan, User, seed_plans

logger = logging.getLogger("ytmoodapi.auth")

REDIS_HOST = os.getenv("REDIS_HOST", "localhost")
REDIS_PORT = int(os.getenv("REDIS_PORT", 6379))

# Redis가 없는 환경(무료 호스팅 등)에서 redis-py는 연결 실패마다 백오프를 두고
# 재시도한다. 그대로 두면 요청 하나가 몇 초씩 서버에서 붙잡힌다. 짧은 타임아웃과
# 쿨다운을 둬서, 실패한 뒤에는 한동안 아예 시도하지 않는다.
REDIS_CONNECT_TIMEOUT_SECONDS = float(os.getenv("REDIS_CONNECT_TIMEOUT_SECONDS", "1"))
REDIS_RETRY_COOLDOWN_SECONDS = float(os.getenv("REDIS_RETRY_COOLDOWN_SECONDS", "60"))

_redis_unavailable_until = 0.0

# Redis is optional: the client is constructed lazily-connecting, so an
# unreachable server does not stop the app from booting. If the package or the
# constructor itself fails we simply run without usage counting.
try:
    import redis

    _client_kwargs = {
        "host": REDIS_HOST,
        "port": REDIS_PORT,
        "decode_responses": True,
        "socket_connect_timeout": REDIS_CONNECT_TIMEOUT_SECONDS,
        "socket_timeout": REDIS_CONNECT_TIMEOUT_SECONDS,
    }
    try:
        from redis.backoff import NoBackoff
        from redis.retry import Retry

        # 기본 재시도 정책은 백오프를 두고 여러 번 재시도한다. Redis가 아예
        # 없는 환경에서는 그 대기가 요청마다 몇 초씩 쌓인다.
        _client_kwargs["retry"] = Retry(NoBackoff(), 0)
    except Exception:
        logger.debug("redis retry policy unavailable; using library defaults")
    redis_client = redis.Redis(**_client_kwargs)
except Exception:
    logger.warning("Redis client unavailable; usage limiting disabled", exc_info=True)
    redis_client = None

DEFAULT_PLAN_NAME = "Free"
ADMIN_PLAN_NAME = "Admin"


def _get_or_create_plan(db, name: str) -> Optional[Plan]:
    plan = db.query(Plan).filter_by(name=name).first()
    if plan:
        return plan
    # seed_plans assigns explicit ids, which leaves plans_id_seq behind; inserting
    # an id-less Plan here would collide with it. Re-run the idempotent seeder.
    try:
        seed_plans(db)
    except IntegrityError:
        db.rollback()
    return db.query(Plan).filter_by(name=name).first()


def _provision(db, api_key: str) -> str:
    """Register an unknown API key under the Free plan and return the plan name."""
    plan = _get_or_create_plan(db, DEFAULT_PLAN_NAME)
    if plan is None:
        raise HTTPException(status_code=503, detail="플랜 정보를 초기화하지 못했습니다")
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


def lookup_plan(api_key: str) -> Optional[str]:
    """등록된 키의 요금제 이름. 등록되지 않은 키면 None (자동 등록하지 않는다)."""
    if not api_key:
        return None
    db = SessionLocal()
    try:
        api_key_obj = db.query(ApiKey).filter_by(key=api_key).first()
        if api_key_obj is None:
            return None
        if api_key_obj.user and api_key_obj.user.plan:
            return api_key_obj.user.plan.name
        return DEFAULT_PLAN_NAME
    finally:
        db.close()


# DB에서 api_key로 요금제 이름 반환 (없는 키는 Free 플랜으로 자동 등록)
def get_plan(api_key: str) -> str:
    plan_name = lookup_plan(api_key)
    if plan_name is not None:
        return plan_name
    db = SessionLocal()
    try:
        # 조회와 등록 사이에 다른 요청이 먼저 등록했을 수 있으므로 한 번 더 확인한다
        if db.query(ApiKey).filter_by(key=api_key).first():
            return lookup_plan(api_key) or DEFAULT_PLAN_NAME
        return _provision(db, api_key)
    finally:
        db.close()


def require_admin(x_api_key: Optional[str] = Header(None)) -> str:
    """
    관리자 전용 엔드포인트 의존성.

    ADMIN_API_KEY 환경변수와 일치하거나, DB에서 Admin 플랜으로 등록된 키만 통과.
    미등록 키를 Free로 자동 등록해버리지 않도록 get_plan이 아니라 lookup_plan을 쓴다.
    """
    if not x_api_key:
        raise HTTPException(status_code=401, detail="X-API-Key 헤더가 필요합니다")
    admin_key = os.getenv("ADMIN_API_KEY")
    if admin_key and secrets.compare_digest(x_api_key, admin_key):
        return x_api_key
    if lookup_plan(x_api_key) == ADMIN_PLAN_NAME:
        return x_api_key
    raise HTTPException(status_code=403, detail="관리자 권한이 필요합니다")


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
    global _redis_unavailable_until
    if redis_client is None:
        return
    if time.monotonic() < _redis_unavailable_until:
        # 최근에 실패했다. 쿨다운이 끝날 때까지 연결을 시도하지 않는다.
        return
    key = f"usage:{api_key}:{plan_name}"
    try:
        count = redis_client.incr(key)
        if count == 1:
            redis_client.expire(key, limits["period"])
    except Exception as exc:
        # Redis down: serve the request rather than failing it. 요청마다 스택
        # 트레이스를 남기면 로그가 금방 가득 차므로 한 줄만 남긴다.
        _redis_unavailable_until = time.monotonic() + REDIS_RETRY_COOLDOWN_SECONDS
        logger.warning(
            "Redis unreachable; skipping usage checks for %ss: %s",
            REDIS_RETRY_COOLDOWN_SECONDS,
            exc,
        )
        return
    if int(count) > limits["limit"]:
        raise HTTPException(status_code=429, detail=f"{plan_name} 플랜 사용량 초과")
