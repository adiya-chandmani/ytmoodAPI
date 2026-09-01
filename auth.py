"""
auth.py: 인증 및 요금제 로직 (Redis 기반 카운팅)
"""
import hashlib
import logging
import os
import secrets
import time
from typing import NamedTuple, Optional

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

# RapidAPI 게이트웨이가 붙여주는 헤더. X-RapidAPI-Key는 구독자마다 고유하므로
# 이것이 호출자 신원이고, X-RapidAPI-Subscription이 실제 결제 등급이다.
RAPIDAPI_PLAN_MAP = {
    "BASIC": "Free",
    "PRO": "Pro",
    "ULTRA": "Business",
    "MEGA": "Mega",
}

# 구독 등급 헤더는 게이트웨이를 거치지 않고 서버로 직접 요청하면 얼마든지 위조할
# 수 있다. RapidAPI가 함께 보내는 프록시 시크릿을 확인할 수 있을 때만 등급을
# 신뢰하고, 그렇지 않으면 신원으로만 쓰고 등급은 무시한다.
RAPIDAPI_PROXY_SECRET_ENV = "RAPIDAPI_PROXY_SECRET"

_warned_about_unverified_subscription = False


class Caller(NamedTuple):
    """이번 요청의 호출자. plan이 있으면 그것이 정본 등급이다."""

    api_key: str
    plan: Optional[str] = None
    username: Optional[str] = None


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


def _provision(db, api_key: str, plan_name: str, username: Optional[str]) -> str:
    """Register an unknown API key and return the plan name it was given."""
    plan = _get_or_create_plan(db, plan_name) or _get_or_create_plan(
        db, DEFAULT_PLAN_NAME
    )
    if plan is None:
        raise HTTPException(status_code=503, detail="플랜 정보를 초기화하지 못했습니다")
    digest = hashlib.sha256(api_key.encode()).hexdigest()
    # 키가 진짜 신원이므로 username은 표시용이다. 키 해시를 섞어 충돌을 막는다.
    username = (
        f"rapidapi_{username}_{digest[:8]}" if username else f"auto_{digest[:32]}"
    )
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


def _sync_plan(db, api_key: str, plan_name: str) -> str:
    """RapidAPI 구독 등급이 바뀌었으면 저장된 플랜을 따라 옮긴다."""
    key_row = db.query(ApiKey).filter_by(key=api_key).first()
    if key_row is None or key_row.user is None:
        return plan_name
    plan = _get_or_create_plan(db, plan_name)
    if plan is None:
        return lookup_plan(api_key) or DEFAULT_PLAN_NAME
    if key_row.user.plan_id != plan.id:
        key_row.user.plan_id = plan.id
        db.commit()
        logger.info("Moved key to plan %s from RapidAPI subscription", plan_name)
    return plan.name


# DB에서 api_key로 요금제 이름 반환 (없는 키는 자동 등록)
def get_plan(
    api_key: str,
    subscription_plan: Optional[str] = None,
    username: Optional[str] = None,
) -> str:
    """
    subscription_plan이 주어지면(검증된 RapidAPI 구독 등급) 그것이 정본이다.
    저장된 플랜이 다르면 그쪽으로 맞춘다.
    """
    plan_name = lookup_plan(api_key)
    if plan_name is not None and subscription_plan is None:
        return plan_name
    db = SessionLocal()
    try:
        if db.query(ApiKey).filter_by(key=api_key).first():
            if subscription_plan is not None:
                return _sync_plan(db, api_key, subscription_plan)
            return lookup_plan(api_key) or DEFAULT_PLAN_NAME
        return _provision(
            db, api_key, subscription_plan or DEFAULT_PLAN_NAME, username
        )
    finally:
        db.close()


def resolve_caller(
    x_rapidapi_key: Optional[str] = Header(None),
    x_rapidapi_user: Optional[str] = Header(None),
    x_rapidapi_subscription: Optional[str] = Header(None),
    x_rapidapi_proxy_secret: Optional[str] = Header(None),
    x_api_key: Optional[str] = Header(None),
) -> Optional[Caller]:
    """
    헤더에서 호출자를 판별한다. RapidAPI를 통해 온 요청이면 구독자별 고유 키를
    신원으로 쓰고, 프록시 시크릿이 확인될 때만 결제 등급까지 반영한다.
    """
    global _warned_about_unverified_subscription

    if x_rapidapi_key:
        expected = os.getenv(RAPIDAPI_PROXY_SECRET_ENV)
        verified = bool(
            expected
            and x_rapidapi_proxy_secret
            and secrets.compare_digest(x_rapidapi_proxy_secret, expected)
        )
        plan = None
        if x_rapidapi_subscription:
            if verified:
                plan = RAPIDAPI_PLAN_MAP.get(x_rapidapi_subscription.strip().upper())
                if plan is None:
                    logger.warning(
                        "Unknown RapidAPI subscription tier %r; using %s",
                        x_rapidapi_subscription,
                        DEFAULT_PLAN_NAME,
                    )
            elif not _warned_about_unverified_subscription:
                _warned_about_unverified_subscription = True
                logger.warning(
                    "Ignoring X-RapidAPI-Subscription because %s is unset or the "
                    "proxy secret did not match; the header is forgeable. Set it "
                    "to enable per-tier limits.",
                    RAPIDAPI_PROXY_SECRET_ENV,
                )
        return Caller(api_key=x_rapidapi_key, plan=plan, username=x_rapidapi_user)

    if x_api_key:
        return Caller(api_key=x_api_key)
    return None


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
    "Mega": {"limit": 500000, "period": 2592000},
    "Admin": {"limit": 1000000, "period": 2592000}
}


def check_usage(
    api_key: str,
    subscription_plan: Optional[str] = None,
    username: Optional[str] = None,
) -> str:
    plan_name = get_plan(api_key, subscription_plan, username)
    limits = PLAN_LIMITS.get(plan_name)
    if limits is None:
        raise HTTPException(status_code=403, detail="지원하지 않는 플랜")
    global _redis_unavailable_until
    if redis_client is None:
        return plan_name
    if time.monotonic() < _redis_unavailable_until:
        # 최근에 실패했다. 쿨다운이 끝날 때까지 연결을 시도하지 않는다.
        return plan_name
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
        return plan_name
    if int(count) > limits["limit"]:
        raise HTTPException(status_code=429, detail=f"{plan_name} 플랜 사용량 초과")
    return plan_name
