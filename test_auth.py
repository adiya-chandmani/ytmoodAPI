from functools import lru_cache

import pytest
from fastapi import HTTPException

import auth
from auth import PLAN_LIMITS, check_usage, get_plan
from db import Base, SessionLocal, engine
from models import ApiKey, Plan, User, seed_plans

FREE_KEY = "test_free_key"
PRO_KEY = "test_pro_key"
BIZ_KEY = "test_biz_key"
UNKNOWN_KEY = "test_unknown_key"

KEY_PLANS = {FREE_KEY: "Free", PRO_KEY: "Pro", BIZ_KEY: "Business"}
ALL_KEYS = list(KEY_PLANS) + [UNKNOWN_KEY]


@lru_cache(maxsize=1)
def _redis_available() -> bool:
    if auth.redis_client is None:
        return False
    try:
        auth.redis_client.ping()
        return True
    except Exception:
        return False


requires_redis = pytest.mark.skipif(
    not _redis_available(), reason="사용량 카운팅 테스트에는 Redis가 필요하다"
)


def _purge_db(db):
    """테스트 키와 그 키가 가리키는 사용자(자동 등록분 포함)를 제거."""
    keys = db.query(ApiKey).filter(ApiKey.key.in_(ALL_KEYS)).all()
    user_ids = {k.user_id for k in keys if k.user_id is not None}
    for key in keys:
        db.delete(key)
    db.flush()
    if user_ids:
        db.query(User).filter(User.id.in_(user_ids)).delete(synchronize_session=False)
    db.query(User).filter(User.username.like("test_user_%")).delete(
        synchronize_session=False
    )
    db.commit()


def _purge_redis():
    # 쿨다운이 남아 있으면 뒤따르는 테스트가 Redis를 건너뛴다
    auth._redis_unavailable_until = 0.0
    if not _redis_available():
        return
    for api_key in ALL_KEYS:
        for plan_name in PLAN_LIMITS:
            auth.redis_client.delete(f"usage:{api_key}:{plan_name}")


@pytest.fixture(autouse=True)
def seeded_keys():
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    try:
        seed_plans(db)
        _purge_db(db)
        for api_key, plan_name in KEY_PLANS.items():
            plan = db.query(Plan).filter_by(name=plan_name).one()
            user = User(username=f"test_user_{plan_name}", plan_id=plan.id)
            db.add(user)
            db.flush()
            db.add(ApiKey(key=api_key, user_id=user.id))
        db.commit()
    finally:
        db.close()
    _purge_redis()

    yield

    db = SessionLocal()
    try:
        _purge_db(db)
    finally:
        db.close()
    _purge_redis()


def test_get_plan_returns_registered_plan():
    assert get_plan(FREE_KEY) == "Free"
    assert get_plan(PRO_KEY) == "Pro"
    assert get_plan(BIZ_KEY) == "Business"


def test_get_plan_auto_registers_unknown_key():
    # 미등록 키는 401이 아니라 Free 플랜으로 자동 등록된다.
    assert get_plan(UNKNOWN_KEY) == "Free"
    # 반복 호출해도 중복 등록되지 않는다.
    assert get_plan(UNKNOWN_KEY) == "Free"
    db = SessionLocal()
    try:
        assert db.query(ApiKey).filter_by(key=UNKNOWN_KEY).count() == 1
    finally:
        db.close()


@requires_redis
@pytest.mark.parametrize(
    "api_key,plan_name",
    [(FREE_KEY, "Free"), (PRO_KEY, "Pro"), (BIZ_KEY, "Business")],
)
def test_check_usage_raises_past_plan_limit(api_key, plan_name):
    limit = PLAN_LIMITS[plan_name]["limit"]
    # ponytail: Pro/Business는 한도가 수만 건이라 실제로 다 호출하면 느리다.
    # 카운터를 경계 직전까지 미리 올려두고 마지막 두 번만 실제로 검증한다.
    auth.redis_client.set(f"usage:{api_key}:{plan_name}", limit - 1)
    check_usage(api_key)  # limit번째 호출: 통과
    with pytest.raises(HTTPException) as excinfo:
        check_usage(api_key)  # limit+1번째 호출: 초과
    assert excinfo.value.status_code == 429


def test_check_usage_passes_when_redis_unavailable(monkeypatch):
    # Redis가 없으면 사용량 제한 없이 통과해야 한다(요청을 실패시키지 않는다).
    monkeypatch.setattr(auth, "redis_client", None)
    for _ in range(PLAN_LIMITS["Free"]["limit"] + 10):
        auth.check_usage(FREE_KEY)


def test_redis_failure_does_not_slow_every_request(monkeypatch):
    """
    배포 환경에서 Redis가 없으면 redis-py가 요청마다 재시도하며 몇 초를 쓴다.
    한 번 실패한 뒤에는 쿨다운 동안 아예 시도하지 않아야 한다.
    """
    import time

    attempts = []

    class _Dead:
        def incr(self, key):
            attempts.append(key)
            time.sleep(0.2)  # 연결 재시도 비용을 흉내낸다
            raise ConnectionError("Connection refused")

        def expire(self, key, ttl):
            raise ConnectionError("Connection refused")

    monkeypatch.setattr(auth, "redis_client", _Dead())
    monkeypatch.setattr(auth, "_redis_unavailable_until", 0.0)
    monkeypatch.setattr(auth, "REDIS_RETRY_COOLDOWN_SECONDS", 30)

    start = time.monotonic()
    for _ in range(10):
        auth.check_usage(FREE_KEY)
    elapsed = time.monotonic() - start

    assert len(attempts) == 1, f"쿨다운을 무시하고 {len(attempts)}번 연결을 시도했다"
    assert elapsed < 1.0
