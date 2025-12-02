# YTmoodAPI

유튜브 댓글 감정 분석/요약 API 백엔드

## 기술 스택
- Python, FastAPI, Redis/Celery, HuggingFace Transformers, OpenAI API, OAuth 2.0, RapidAPI 배포

## 주요 구조
- main.py: FastAPI 진입점
- comment_collector.py: 유튜브 댓글 수집
- sentiment_analyzer.py: 감정 분석
- profanity_detector.py: 욕설 감지
- keyword_extractor.py: 키워드 추출
- auth.py: 인증/요금제 로직
- tests/: 테스트 코드


## 인증 및 요금제
- 모든 요청은 API 키 필요 (환경변수 또는 요청값)
- 플랜별 사용량 제한:
  - Free: 하루 100개
  - Pro: 월 30,000개
  - Business: 월 100,000개
- 초과 시 429 에러 반환
- 응답 내 plan 필드로 현재 플랜 확인 가능
- 환경변수 예시:
  - FREE_API_KEY, PRO_API_KEY, BUSINESS_API_KEY

## API 사용 예시

### 댓글 분석 및 요약
- **POST** `/analyze-comments`
- 요청 예시:
```json
{
  "youtube_video_id": "dQw4w9WgXcQ",
  "lang": "en",
  "api_key": "your_api_key"
}
```
- 응답 예시:
```json
{
  "summary": {"positive": 64, "neutral": 21, "negative": 15},
  "keywords": ["목소리", "편집", "사랑해요"],
  "highlighted_comments": {
    "positive": ["진짜 잘했어요!", "계속 보고 싶어요!"],
    "negative": ["내용이 너무 지루해요", "이건 좀 별로네요"]
  },
  "plan": "Free"
}
```

## 환경변수 설정
- .env 파일에 YOUTUBE_API_KEY 등 주요 키를 설정

## 테스트 실행
```bash
pytest tests/
``` 

## 배포 및 피드백

### RapidAPI 배포 방법
- RapidAPI에 회원가입 후, 새 API 프로젝트 생성
- main.py의 FastAPI 앱을 Uvicorn 등으로 실행 후, RapidAPI에서 엔드포인트 등록
- RapidAPI 대시보드에서 테스트 및 문서화 진행
- 예시: https://rapidapi.com/your-username/api/ytmoodapi

### 주요 엔드포인트
- POST /analyze-comments: 유튜브 댓글 분석 및 요약

### 피드백/이슈 기록 예시
- [2025-07-17] MVP 런칭, 첫 사용자 피드백 수집 시작
- [2025-07-18] Free 플랜 일일 제한 관련 문의 다수 접수

### 프로젝트 마무리
- 모든 기능 및 문서화, 테스트 완료
- 추가 피드백 및 개선 요청은 이슈 트래커 또는 RapidAPI 피드백 기능 활용 

## Docker 개발환경

### 준비물
- Docker, Docker Compose 설치

### 환경변수 설정
- .env 파일을 .env.example 참고해 작성

### 컨테이너 실행
```bash
docker-compose up --build
```
- FastAPI: http://localhost:8000
- Redis: localhost:6379
- PostgreSQL: localhost:5432

### 컨테이너 중지
```bash
docker-compose down
```

### 컨테이너 내부 접속 예시
```bash
docker exec -it ytmoodapi_app /bin/bash
```

### 기타
- Redis/PostgreSQL 연동은 환경변수로 자동 연결
- FastAPI 앱은 0.0.0.0:8000에서 기동
- DB 마이그레이션/초기화는 추후 안내 

## PostgreSQL 연동

### DB 테이블 생성 (마이그레이션)
```bash
# 컨테이너 내부 진입
# docker exec -it ytmoodapi_app /bin/bash
# Python 셸에서 아래 실행
python
>>> from db import Base, engine
>>> import models
>>> Base.metadata.create_all(bind=engine)
```

### 주요 테이블/모델
- User, Plan, ApiKey, AnalysisResult (models.py 참고)

### DB CRUD 예시 (Python)
```python
from db import SessionLocal
from models import User

db = SessionLocal()
user = User(username="testuser", plan_id=1)
db.add(user)
db.commit()
db.refresh(user)
print(user.id)
db.close()
```

### SQLAlchemy 공식 문서
- https://docs.sqlalchemy.org/ 

## 운영 자동화 및 통합 테스트

### 전체 기능 통합 테스트
- 모든 컨테이너가 실행 중일 때 아래 명령어로 전체 테스트 실행
```bash
PYTHONPATH=. pytest
```
- 각 기능별 테스트 코드가 통합적으로 실행됨

### CI/CD 예시 (GitHub Actions)
- .github/workflows/ci.yml 파일 예시:
```yaml
name: CI
on: [push, pull_request]
jobs:
  test:
    runs-on: ubuntu-latest
    services:
      postgres:
        image: postgres:14
        env:
          POSTGRES_USER: ytmood
          POSTGRES_PASSWORD: ytmoodpw
          POSTGRES_DB: ytmood
        ports: [5432:5432]
      redis:
        image: redis:7
        ports: [6379:6379]
    steps:
      - uses: actions/checkout@v3
      - name: Set up Python
        uses: actions/setup-python@v4
        with:
          python-version: '3.10'
      - name: Install dependencies
        run: |
          pip install -r requirements.txt
      - name: Run tests
        run: |
          PYTHONPATH=. pytest
```

### 환경변수/시크릿 관리
- .env.example 참고, 실제 운영 환경에서는 시크릿/환경변수로 관리

### 보안 점검
- DB/Redis 비밀번호, API 키 등은 코드에 하드코딩하지 않고 환경변수로만 관리
- 운영 환경에서는 DEBUG/개발 옵션 비활성화 
