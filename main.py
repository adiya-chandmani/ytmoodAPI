"""
main.py: YTmoodAPI FastAPI 진입점
"""
import json
import logging
import os
import secrets
from collections import Counter
from contextlib import asynccontextmanager
from typing import List, Optional

from fastapi import Depends, FastAPI, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from auth import Caller, check_usage, get_plan, require_admin, resolve_caller
from comment_collector import CommentCollectionError, collect_comments
from db import Base, SessionLocal, engine, get_db
from keyword_extractor import extract_keywords
from models import AnalysisResult, ApiKey, Plan, User, seed_plans
from profanity_detector import detect_profanity
from sentiment_analyzer import analyze_sentiment

logger = logging.getLogger("ytmoodapi.main")

SENTIMENT_LABELS = ("positive", "neutral", "negative")
HIGHLIGHT_COUNT = 2


@asynccontextmanager
async def lifespan(app: FastAPI):
    """배포 환경에는 수동 마이그레이션용 셸이 없으므로 기동 시 자동 초기화한다."""
    try:
        Base.metadata.create_all(bind=engine)
        db = SessionLocal()
        try:
            seed_plans(db)
        finally:
            db.close()
    except Exception:
        logger.exception("Startup DB initialization failed")
    yield


app = FastAPI(title="YTmoodAPI", lifespan=lifespan)


class AnalyzeRequest(BaseModel):
    youtube_video_id: str
    lang: str = "en"
    api_key: Optional[str] = None


class UserCreate(BaseModel):
    username: str
    plan_id: int


class ApiKeyOut(BaseModel):
    api_key: str


class WhoAmIOut(BaseModel):
    api_key: str
    plan: str
    user_id: Optional[int] = None


@app.get("/")
@app.get("/health")
def health():
    return {"status": "ok", "service": "YTMoodAPI"}


def summarize(comments: List[str]) -> dict:
    # 댓글마다 감정 분석을 한 번만 수행한다. 예전에는 요약/긍정/부정 구간에서
    # 각각 다시 호출해 댓글 수의 3배만큼 추론이 돌았다.
    sentiments = [analyze_sentiment(c) for c in comments]
    total = len(sentiments) or 1
    counts = Counter(sentiments)
    summary = {
        label: int(counts[label] * 100 / total) for label in SENTIMENT_LABELS
    }
    highlighted = {
        label: [c for c, s in zip(comments, sentiments) if s == label][:HIGHLIGHT_COUNT]
        for label in ("positive", "negative")
    }
    return {
        "summary": summary,
        "keywords": extract_keywords(comments),
        "highlighted_comments": highlighted,
        "profanity_count": sum(1 for c in comments if detect_profanity(c)),
    }


def _store_result(db: Session, api_key: str, video_id: str, result: dict) -> None:
    """분석 결과를 보관한다. 실패해도 응답은 정상 반환한다."""
    try:
        key_row = db.query(ApiKey).filter_by(key=api_key).first()
        db.add(
            AnalysisResult(
                user_id=key_row.user_id if key_row else None,
                video_id=video_id,
                result_json=json.dumps(result, ensure_ascii=False),
            )
        )
        db.commit()
    except Exception:
        db.rollback()
        logger.exception("Failed to store analysis result")


@app.post("/analyze-comments")
def analyze_comments(
    req: AnalyzeRequest,
    caller: Optional[Caller] = Depends(resolve_caller),
    db: Session = Depends(get_db),
):
    # 호출자 키(요금제/사용량)와 YouTube Data API 키는 서로 다른 것이다.
    # 예전에는 하나의 값을 양쪽에 모두 써서, RapidAPI 구독자 키로는 댓글을
    # 가져올 수 없었고 반대로 서버 키가 사용자로 등록되기도 했다.
    # 헤더로 신원을 못 찾으면 본문의 api_key로 넘어간다(직접 호출용).
    if caller is None and req.api_key:
        caller = Caller(api_key=req.api_key)
    if caller is None:
        raise HTTPException(status_code=401, detail="API 키가 필요합니다.")
    client_key = caller.api_key
    plan = check_usage(client_key, caller.plan, caller.username)

    youtube_key = os.getenv("YOUTUBE_API_KEY")
    if not youtube_key:
        raise HTTPException(
            status_code=503, detail="서버에 YOUTUBE_API_KEY가 설정되지 않았습니다."
        )

    try:
        comments = collect_comments(req.youtube_video_id, youtube_key)
    except CommentCollectionError as exc:
        # 수집 실패를 '댓글 0개'로 위장하지 않는다
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    result = summarize(comments)
    result["plan"] = plan
    _store_result(db, client_key, req.youtube_video_id, result)
    return result


# 내 API 키/플랜 조회 (호출자 본인의 키 기준)
@app.get("/apikeys/me", response_model=WhoAmIOut)
def get_my_apikey(
    caller: Optional[Caller] = Depends(resolve_caller),
    db: Session = Depends(get_db),
):
    if caller is None:
        raise HTTPException(
            status_code=401, detail="X-RapidAPI-Key 또는 X-API-Key 헤더가 필요합니다"
        )
    # get_plan이 미등록 키를 먼저 등록하므로, 그 뒤에 조회해야 user_id가 채워진다
    plan = get_plan(caller.api_key, caller.plan, caller.username)
    key_row = db.query(ApiKey).filter_by(key=caller.api_key).first()
    return {
        "api_key": caller.api_key,
        "plan": plan,
        "user_id": key_row.user_id if key_row else None,
    }


# --- 관리자 전용 --------------------------------------------------------------
# 아래 엔드포인트는 키 발급/열람/삭제가 가능하므로 전부 관리자 인증을 요구한다.


@app.post("/users", response_model=dict)
def create_user(
    user: UserCreate,
    db: Session = Depends(get_db),
    _admin: str = Depends(require_admin),
):
    if not db.query(Plan).filter_by(id=user.plan_id).first():
        raise HTTPException(status_code=400, detail="존재하지 않는 plan_id")
    db_user = User(username=user.username, plan_id=user.plan_id)
    db.add(db_user)
    db.commit()
    db.refresh(db_user)
    return {"user_id": db_user.id}


@app.post("/apikeys", response_model=ApiKeyOut)
def create_apikey(
    user_id: int,
    db: Session = Depends(get_db),
    _admin: str = Depends(require_admin),
):
    if not db.query(User).filter_by(id=user_id).first():
        raise HTTPException(status_code=404, detail="존재하지 않는 user_id")
    api_key = ApiKey(key=secrets.token_urlsafe(32), user_id=user_id)
    db.add(api_key)
    db.commit()
    db.refresh(api_key)
    return {"api_key": api_key.key}


@app.get("/apikeys", response_model=list)
def list_apikeys(
    db: Session = Depends(get_db), _admin: str = Depends(require_admin)
):
    return [
        {"api_key": k.key, "user_id": k.user_id} for k in db.query(ApiKey).all()
    ]


@app.delete("/apikeys/{key}", response_model=dict)
def delete_apikey(
    key: str, db: Session = Depends(get_db), _admin: str = Depends(require_admin)
):
    api_key = db.query(ApiKey).filter_by(key=key).first()
    if not api_key:
        raise HTTPException(status_code=404, detail="API key not found")
    db.delete(api_key)
    db.commit()
    return {"deleted": key}
