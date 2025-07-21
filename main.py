from fastapi import FastAPI, HTTPException, Depends
from pydantic import BaseModel
from comment_collector import collect_comments
from sentiment_analyzer import analyze_sentiment
from profanity_detector import detect_profanity
from keyword_extractor import extract_keywords
from auth import check_usage, get_plan
import os
from collections import Counter
from db import SessionLocal
from models import User, ApiKey
import secrets

app = FastAPI()

"""
main.py: YTmoodAPI FastAPI 진입점
"""

class AnalyzeRequest(BaseModel):
    youtube_video_id: str
    lang: str = "en"
    api_key: str = None

class UserCreate(BaseModel):
    username: str
    plan_id: int

class ApiKeyOut(BaseModel):
    api_key: str

def summarize(comments):
    sentiments = [analyze_sentiment(c) for c in comments]
    total = len(sentiments) or 1
    summary = {
        "positive": int(sentiments.count("positive") * 100 / total),
        "neutral": int(sentiments.count("neutral") * 100 / total) if "neutral" in sentiments else 0,
        "negative": int(sentiments.count("negative") * 100 / total)
    }
    highlighted_comments = {
        "positive": [c for c in comments if analyze_sentiment(c) == "positive"][:2],
        "negative": [c for c in comments if analyze_sentiment(c) == "negative"][:2]
    }
    keywords = extract_keywords(comments)
    return {
        "summary": summary,
        "keywords": keywords,
        "highlighted_comments": highlighted_comments
    }

@app.post("/analyze-comments")
def analyze_comments(req: AnalyzeRequest):
    api_key = req.api_key or os.getenv("YOUTUBE_API_KEY")
    if not api_key:
        raise HTTPException(status_code=400, detail="API 키가 필요합니다.")
    check_usage(api_key)
    comments = collect_comments(req.youtube_video_id, api_key)
    result = summarize(comments)
    result["plan"] = get_plan(api_key)
    return result

# 추후 요약/대표댓글/비율 등 추가 예정 

# 회원가입
@app.post("/users", response_model=dict)
def create_user(user: UserCreate):
    db = SessionLocal()
    db_user = User(username=user.username, plan_id=user.plan_id)
    db.add(db_user)
    db.commit()
    db.refresh(db_user)
    db.close()
    return {"user_id": db_user.id}

# API 키 발급
@app.post("/apikeys", response_model=ApiKeyOut)
def create_apikey(user_id: int):
    db = SessionLocal()
    key = secrets.token_urlsafe(32)
    api_key = ApiKey(key=key, user_id=user_id)
    db.add(api_key)
    db.commit()
    db.refresh(api_key)
    db.close()
    return {"api_key": api_key.key}

# 내 API 키 조회
@app.get("/apikeys/me", response_model=ApiKeyOut)
def get_my_apikey(user_id: int):
    db = SessionLocal()
    api_key = db.query(ApiKey).filter_by(user_id=user_id).first()
    db.close()
    if not api_key:
        raise HTTPException(status_code=404, detail="API key not found")
    return {"api_key": api_key.key}

# (관리자) 전체 키 조회
@app.get("/apikeys", response_model=list)
def list_apikeys():
    db = SessionLocal()
    keys = db.query(ApiKey).all()
    db.close()
    return [{"api_key": k.key, "user_id": k.user_id} for k in keys]

# (관리자) 키 삭제
@app.delete("/apikeys/{key}", response_model=dict)
def delete_apikey(key: str):
    db = SessionLocal()
    api_key = db.query(ApiKey).filter_by(key=key).first()
    if not api_key:
        db.close()
        raise HTTPException(status_code=404, detail="API key not found")
    db.delete(api_key)
    db.commit()
    db.close()
    return {"deleted": key} 