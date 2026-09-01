"""관리자 인증과 키 분리 동작에 대한 엔드포인트 테스트."""
import pytest
from fastapi.testclient import TestClient

import comment_collector
import main
from db import Base, SessionLocal, engine
from models import AnalysisResult, ApiKey, Plan, User, seed_plans

ADMIN_KEY = "test_admin_key"
CLIENT_KEY = "test_client_key"
YT_KEY = "server_side_youtube_key"


@pytest.fixture(autouse=True)
def prepared_db(monkeypatch):
    monkeypatch.setenv("ADMIN_API_KEY", ADMIN_KEY)
    monkeypatch.setenv("YOUTUBE_API_KEY", YT_KEY)
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    try:
        seed_plans(db)
        _purge(db)
    finally:
        db.close()
    yield
    db = SessionLocal()
    try:
        _purge(db)
    finally:
        db.close()


def _purge(db):
    for key in (CLIENT_KEY, ADMIN_KEY, YT_KEY):
        row = db.query(ApiKey).filter_by(key=key).first()
        if row:
            user_id = row.user_id
            db.delete(row)
            db.flush()
            # analysis_results가 users를 참조하므로 먼저 정리한다
            db.query(AnalysisResult).filter_by(user_id=user_id).delete(
                synchronize_session=False
            )
            db.query(User).filter_by(id=user_id).delete()
    db.query(User).filter(User.username.like("endpoint_test_%")).delete(
        synchronize_session=False
    )
    db.commit()


@pytest.fixture
def client():
    with TestClient(main.app) as c:
        yield c


def test_health(client):
    assert client.get("/health").json()["status"] == "ok"


def test_admin_endpoints_reject_anonymous(client):
    assert client.get("/apikeys").status_code == 401
    assert client.post("/apikeys?user_id=1").status_code == 401
    assert client.delete("/apikeys/whatever").status_code == 401
    assert client.post("/users", json={"username": "x", "plan_id": 1}).status_code == 401


def test_admin_endpoints_reject_non_admin_key(client):
    headers = {"X-API-Key": CLIENT_KEY}
    assert client.get("/apikeys", headers=headers).status_code == 403
    assert client.delete("/apikeys/whatever", headers=headers).status_code == 403


def test_rejecting_a_non_admin_key_does_not_register_it(client):
    client.get("/apikeys", headers={"X-API-Key": CLIENT_KEY})
    db = SessionLocal()
    try:
        # require_admin은 lookup_plan을 쓰므로 미등록 키를 Free로 만들지 않는다
        assert db.query(ApiKey).filter_by(key=CLIENT_KEY).first() is None
    finally:
        db.close()


def test_admin_key_can_manage_keys(client):
    headers = {"X-API-Key": ADMIN_KEY}
    created = client.post(
        "/users", json={"username": "endpoint_test_user", "plan_id": 1}, headers=headers
    )
    assert created.status_code == 200
    user_id = created.json()["user_id"]

    issued = client.post(f"/apikeys?user_id={user_id}", headers=headers)
    assert issued.status_code == 200
    new_key = issued.json()["api_key"]

    listed = client.get("/apikeys", headers=headers).json()
    assert any(k["api_key"] == new_key for k in listed)

    assert client.delete(f"/apikeys/{new_key}", headers=headers).status_code == 200


def test_create_user_rejects_unknown_plan(client):
    resp = client.post(
        "/users",
        json={"username": "endpoint_test_bad", "plan_id": 12345},
        headers={"X-API-Key": ADMIN_KEY},
    )
    assert resp.status_code == 400


def test_analyze_requires_a_key(client):
    resp = client.post("/analyze-comments", json={"youtube_video_id": "vid"})
    assert resp.status_code == 401


def test_analyze_uses_server_youtube_key_not_the_caller_key(client, monkeypatch):
    seen = {}

    def _fake_collect(video_id, api_key, max_results=50):
        seen["video_id"] = video_id
        seen["api_key"] = api_key
        return ["awesome video", "terrible video"]

    monkeypatch.setattr(main, "collect_comments", _fake_collect)
    resp = client.post(
        "/analyze-comments",
        json={"youtube_video_id": "vid123", "api_key": CLIENT_KEY},
    )
    assert resp.status_code == 200
    # 호출자 키가 아니라 서버의 YOUTUBE_API_KEY로 유튜브를 호출해야 한다
    assert seen["api_key"] == YT_KEY
    assert seen["video_id"] == "vid123"
    assert resp.json()["plan"] == "Free"


def test_analyze_surfaces_collection_failure_as_502(client, monkeypatch):
    def _boom(*a, **k):
        raise comment_collector.CommentCollectionError("API key not valid")

    monkeypatch.setattr(main, "collect_comments", _boom)
    resp = client.post(
        "/analyze-comments",
        json={"youtube_video_id": "vid", "api_key": CLIENT_KEY},
    )
    assert resp.status_code == 502


def test_analyze_requires_server_youtube_key(client, monkeypatch):
    monkeypatch.delenv("YOUTUBE_API_KEY", raising=False)
    resp = client.post(
        "/analyze-comments",
        json={"youtube_video_id": "vid", "api_key": CLIENT_KEY},
    )
    assert resp.status_code == 503


def test_whoami_uses_caller_key(client):
    resp = client.get("/apikeys/me", headers={"X-API-Key": CLIENT_KEY})
    assert resp.status_code == 200
    body = resp.json()
    assert body["api_key"] == CLIENT_KEY
    assert body["plan"] == "Free"
    # 첫 호출에서 자동 등록되므로 user_id가 채워져 있어야 한다
    assert body["user_id"] is not None
    assert client.get("/apikeys/me").status_code == 401
