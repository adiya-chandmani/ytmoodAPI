"""RapidAPI 게이트웨이 헤더 처리."""
import pytest
from fastapi.testclient import TestClient

import auth
import main
from db import Base, SessionLocal, engine
from models import AnalysisResult, ApiKey, Plan, User, seed_plans

PROXY_SECRET = "test_proxy_secret"
SUB_A = "rapidapi_key_subscriber_a"
SUB_B = "rapidapi_key_subscriber_b"
ALL_KEYS = [SUB_A, SUB_B]


def _purge():
    db = SessionLocal()
    try:
        for key in ALL_KEYS:
            row = db.query(ApiKey).filter_by(key=key).first()
            if row:
                user_id = row.user_id
                db.delete(row)
                db.flush()
                db.query(AnalysisResult).filter_by(user_id=user_id).delete(
                    synchronize_session=False
                )
                db.query(User).filter_by(id=user_id).delete()
        db.commit()
    finally:
        db.close()


@pytest.fixture(autouse=True)
def prepared(monkeypatch):
    monkeypatch.setenv("YOUTUBE_API_KEY", "server_yt_key")
    monkeypatch.setattr(auth, "redis_client", None)  # 사용량 제한은 여기서 관심 밖
    monkeypatch.setattr(auth, "_warned_about_unverified_subscription", False)
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    try:
        seed_plans(db)
    finally:
        db.close()
    _purge()
    yield
    _purge()


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(
        main, "collect_comments", lambda v, k, max_results=50: ["awesome video"]
    )
    with TestClient(main.app) as c:
        yield c


def _headers(key, subscription=None, user=None, secret=PROXY_SECRET):
    h = {"X-RapidAPI-Key": key}
    if subscription:
        h["X-RapidAPI-Subscription"] = subscription
    if user:
        h["X-RapidAPI-User"] = user
    if secret:
        h["X-RapidAPI-Proxy-Secret"] = secret
    return h


def _plan_of(key):
    db = SessionLocal()
    try:
        row = db.query(ApiKey).filter_by(key=key).first()
        return row.user.plan.name if row and row.user and row.user.plan else None
    finally:
        db.close()


def test_subscribers_get_their_own_accounts(client, monkeypatch):
    monkeypatch.setenv("RAPIDAPI_PROXY_SECRET", PROXY_SECRET)
    body = {"youtube_video_id": "v"}
    client.post("/analyze-comments", json=body, headers=_headers(SUB_A, "BASIC", "alice"))
    client.post("/analyze-comments", json=body, headers=_headers(SUB_B, "PRO", "bob"))

    db = SessionLocal()
    try:
        a = db.query(ApiKey).filter_by(key=SUB_A).first()
        b = db.query(ApiKey).filter_by(key=SUB_B).first()
        assert a is not None and b is not None
        # 예전에는 헤더를 안 읽어서 구독자가 한 계정으로 뭉쳤다
        assert a.user_id != b.user_id
    finally:
        db.close()


@pytest.mark.parametrize(
    "tier,expected",
    [("BASIC", "Free"), ("PRO", "Pro"), ("ULTRA", "Business"), ("MEGA", "Mega")],
)
def test_subscription_tier_maps_to_plan(client, monkeypatch, tier, expected):
    monkeypatch.setenv("RAPIDAPI_PROXY_SECRET", PROXY_SECRET)
    resp = client.post(
        "/analyze-comments",
        json={"youtube_video_id": "v"},
        headers=_headers(SUB_A, tier, "alice"),
    )
    assert resp.status_code == 200
    assert resp.json()["plan"] == expected
    assert _plan_of(SUB_A) == expected


def test_upgrade_is_followed(client, monkeypatch):
    monkeypatch.setenv("RAPIDAPI_PROXY_SECRET", PROXY_SECRET)
    body = {"youtube_video_id": "v"}
    client.post("/analyze-comments", json=body, headers=_headers(SUB_A, "BASIC"))
    assert _plan_of(SUB_A) == "Free"
    # 구독자가 업그레이드하면 저장된 플랜도 따라가야 한다
    r = client.post("/analyze-comments", json=body, headers=_headers(SUB_A, "ULTRA"))
    assert r.json()["plan"] == "Business"
    assert _plan_of(SUB_A) == "Business"
    # 다운그레이드도 마찬가지
    r = client.post("/analyze-comments", json=body, headers=_headers(SUB_A, "BASIC"))
    assert r.json()["plan"] == "Free"


def test_forged_subscription_without_proxy_secret_is_ignored(client, monkeypatch):
    monkeypatch.setenv("RAPIDAPI_PROXY_SECRET", PROXY_SECRET)
    # 게이트웨이를 우회해 직접 MEGA를 주장하는 요청
    resp = client.post(
        "/analyze-comments",
        json={"youtube_video_id": "v"},
        headers=_headers(SUB_A, "MEGA", secret=None),
    )
    assert resp.status_code == 200
    assert resp.json()["plan"] == "Free"
    assert _plan_of(SUB_A) == "Free"


def test_wrong_proxy_secret_is_ignored(client, monkeypatch):
    monkeypatch.setenv("RAPIDAPI_PROXY_SECRET", PROXY_SECRET)
    resp = client.post(
        "/analyze-comments",
        json={"youtube_video_id": "v"},
        headers=_headers(SUB_A, "MEGA", secret="wrong"),
    )
    assert resp.json()["plan"] == "Free"


def test_subscription_ignored_when_secret_not_configured(client, monkeypatch):
    monkeypatch.delenv("RAPIDAPI_PROXY_SECRET", raising=False)
    # 시크릿을 설정하지 않았으면 등급을 검증할 방법이 없으므로 신뢰하지 않는다
    resp = client.post(
        "/analyze-comments",
        json={"youtube_video_id": "v"},
        headers=_headers(SUB_A, "MEGA"),
    )
    assert resp.json()["plan"] == "Free"
    # 신원은 그대로 쓰이므로 구독자별 계정 분리는 유지된다
    assert _plan_of(SUB_A) == "Free"


def test_unknown_tier_falls_back_to_free(client, monkeypatch):
    monkeypatch.setenv("RAPIDAPI_PROXY_SECRET", PROXY_SECRET)
    resp = client.post(
        "/analyze-comments",
        json={"youtube_video_id": "v"},
        headers=_headers(SUB_A, "PLATINUM_DELUXE"),
    )
    assert resp.json()["plan"] == "Free"


def test_rapidapi_key_wins_over_x_api_key(client, monkeypatch):
    monkeypatch.setenv("RAPIDAPI_PROXY_SECRET", PROXY_SECRET)
    headers = _headers(SUB_A, "PRO")
    headers["X-API-Key"] = SUB_B
    client.post("/analyze-comments", json={"youtube_video_id": "v"}, headers=headers)
    assert _plan_of(SUB_A) == "Pro"
    assert _plan_of(SUB_B) is None


def test_direct_x_api_key_still_works(client):
    resp = client.post(
        "/analyze-comments",
        json={"youtube_video_id": "v"},
        headers={"X-API-Key": SUB_A},
    )
    assert resp.status_code == 200
    assert resp.json()["plan"] == "Free"


def test_body_api_key_still_works(client):
    resp = client.post(
        "/analyze-comments", json={"youtube_video_id": "v", "api_key": SUB_A}
    )
    assert resp.status_code == 200


def test_whoami_uses_rapidapi_identity(client, monkeypatch):
    monkeypatch.setenv("RAPIDAPI_PROXY_SECRET", PROXY_SECRET)
    resp = client.get("/apikeys/me", headers=_headers(SUB_A, "ULTRA", "alice"))
    assert resp.status_code == 200
    body = resp.json()
    assert body["api_key"] == SUB_A
    assert body["plan"] == "Business"
    assert body["user_id"] is not None


def test_usage_limit_uses_the_subscribed_tier(monkeypatch):
    # Mega 등급은 Free보다 훨씬 큰 한도를 받아야 한다
    assert auth.PLAN_LIMITS["Mega"]["limit"] > auth.PLAN_LIMITS["Free"]["limit"]
    assert auth.RAPIDAPI_PLAN_MAP["MEGA"] == "Mega"
