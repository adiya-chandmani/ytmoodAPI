# YTmoodAPI

유튜브 댓글 감정 분석/요약 API 백엔드

## 기술 스택
- Python, FastAPI, PostgreSQL(SQLAlchemy), Redis(선택), HuggingFace Transformers

Redis가 없으면 사용량 제한 없이 동작하고, 감정 분석 모델을 제한 시간 안에
불러오지 못하면 사전 기반 폴백으로 전환된다. 둘 다 앱 기동도, 응답도 막지 않는다.

### 느린 환경에서의 동작

무료/저사양 호스팅에서는 두 가지가 요청을 붙잡을 수 있어 각각 상한을 뒀다.

| 상황 | 동작 |
|---|---|
| 모델 다운로드가 `SENTIMENT_MODEL_TIMEOUT_SECONDS`(기본 8초)를 넘김 | 즉시 포기하고 사전 폴백. 프로세스가 사는 동안 재시도하지 않음 |
| Redis 연결 실패 | 사용량 검사를 건너뜀. 이후 `REDIS_RETRY_COOLDOWN_SECONDS`(기본 60초) 동안 재연결 시도 안 함 |

첫 요청만 모델 대기 시간을 한 번 치르고, 이후 요청은 즉시 응답한다. 더 빠른
플랜으로 올리면 제한 시간 안에 모델이 올라와 RoBERTa 추론이 자동으로 켜진다.

## 주요 구조
- `main.py`: FastAPI 진입점
- `comment_collector.py`: 유튜브 댓글 수집
- `sentiment_analyzer.py`: 감정 분석 (지연 로딩 + 사전 폴백)
- `profanity_detector.py`: 욕설 감지
- `keyword_extractor.py`: 키워드 추출 (한국어/영어)
- `auth.py`: 인증/요금제 로직
- `db.py`, `models.py`: DB 연결과 스키마
- `test_*.py`: 저장소 루트의 테스트 코드

## API 키 두 종류

혼동하기 쉬우므로 분리해서 관리한다.

| 키 | 위치 | 용도 |
|---|---|---|
| `YOUTUBE_API_KEY` | 서버 환경변수 | YouTube Data API 호출. 클라이언트가 보내지 않는다. |
| 호출자 키 | `X-RapidAPI-Key` 헤더, 없으면 `X-API-Key` 헤더, 없으면 본문 `api_key` | 요금제 판별과 사용량 카운팅 |
| `ADMIN_API_KEY` | 서버 환경변수 | 관리자 엔드포인트 접근 |

처음 보는 호출자 키는 401이 아니라 자동 등록된다. RapidAPI 구독자가 사전에
가입 절차를 밟을 수 없기 때문이다.

### RapidAPI 연동

게이트웨이가 붙여주는 헤더를 읽는다.

| 헤더 | 쓰임 |
|---|---|
| `X-RapidAPI-Key` | 구독자마다 고유. 이것이 호출자 신원이다 |
| `X-RapidAPI-User` | 자동 생성되는 사용자 이름에 사용 (표시용) |
| `X-RapidAPI-Subscription` | 결제 등급. 아래 표대로 플랜에 매핑된다 |
| `X-RapidAPI-Proxy-Secret` | 등급 헤더를 신뢰해도 되는지 검증 |

| RapidAPI 등급 | 플랜 | 한도 |
|---|---|---|
| BASIC | Free | 100 / 일 |
| PRO | Pro | 30,000 / 월 |
| ULTRA | Business | 100,000 / 월 |
| MEGA | Mega | 500,000 / 월 |

구독 등급이 바뀌면 다음 요청에서 저장된 플랜도 따라 옮겨간다(업그레이드/다운그레이드 모두).

**`RAPIDAPI_PROXY_SECRET`을 반드시 설정할 것.** `X-RapidAPI-Subscription`은
게이트웨이를 우회해 서버로 직접 요청하면 누구나 위조할 수 있는 값이다. 그래서
이 시크릿이 설정되어 있고 요청의 `X-RapidAPI-Proxy-Secret`과 일치할 때만 등급을
반영한다. 설정하지 않으면 구독자 구분은 계속 되지만 등급은 무시되고 전부 Free
한도를 받는다. RapidAPI 대시보드의 프록시 시크릿 값을 Render 환경변수에 그대로
넣으면 된다.

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
  "profanity_count": 0,
  "plan": "Free"
}
```

| 상태 코드 | 의미 |
|---|---|
| 401 | 호출자 키 없음 |
| 429 | 요금제 사용량 초과 |
| 502 | 유튜브에서 댓글을 가져오지 못함 (키 오류, 할당량 초과 등) |
| 503 | 서버에 `YOUTUBE_API_KEY` 미설정 |

### 내 키/플랜 조회
- **GET** `/apikeys/me` — `X-API-Key` 헤더의 키를 기준으로 조회한다

### 헬스 체크
- **GET** `/health`, **GET** `/` — `{"status": "ok", "service": "YTMoodAPI"}`

### 관리자 전용
`X-API-Key` 헤더에 `ADMIN_API_KEY` 값 또는 Admin 플랜 키가 필요하다.

- **POST** `/users` — 사용자 생성
- **POST** `/apikeys?user_id=<id>` — 키 발급
- **GET** `/apikeys` — 전체 키 조회
- **DELETE** `/apikeys/{key}` — 키 삭제

## 환경변수 설정
`.env.example`을 복사해 `.env`를 만든다. `DATABASE_URL`이 있으면 그것을 쓰고,
없으면 `POSTGRES_*` 값을 조합한다.

## 테스트 실행
```bash
PYTHONPATH=. pytest
```
PostgreSQL이 필요하다. Redis가 없으면 사용량 관련 테스트는 자동으로 건너뛴다.

**주의:** 테스트는 `DATABASE_URL`이 가리키는 DB에 직접 쓴다. 운영 DB를 가리킨
채로 실행하지 말 것.

## Docker 개발환경

### 준비물
- Docker, Docker Compose

### 실행
```bash
cp .env.example .env   # YOUTUBE_API_KEY, ADMIN_API_KEY 채우기
docker-compose up --build
```
- FastAPI: http://localhost:8000 (문서: http://localhost:8000/docs)
- Redis: localhost:6379
- PostgreSQL: localhost:5432

### 중지
```bash
docker-compose down
```

## DB 초기화

수동 마이그레이션은 필요 없다. 앱이 기동할 때 `Base.metadata.create_all`로
테이블을 만들고 기본 플랜(Free/Pro/Business/Admin)을 심는다.

### 주요 테이블/모델
`User`, `Plan`, `ApiKey`, `AnalysisResult` (`models.py` 참고).
분석 결과는 `analysis_results`에 자동으로 쌓인다.

## 배포

### Render
저장소 루트의 `render.yaml`이 웹 서비스와 PostgreSQL을 함께 프로비저닝한다.
`DATABASE_URL`은 DB에서 자동 연결되고, `YOUTUBE_API_KEY`와 `ADMIN_API_KEY`는
대시보드에서 직접 입력한다.

### RapidAPI
- 배포된 URL을 RapidAPI에 엔드포인트로 등록
- 구독자 키는 `X-API-Key` 헤더로 전달되며 첫 호출 때 Free 플랜으로 등록된다

### CI (GitHub Actions 예시)
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
        options: >-
          --health-cmd pg_isready --health-interval 5s
          --health-timeout 5s --health-retries 10
      redis:
        image: redis:7
        ports: [6379:6379]
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: '3.10'
      - run: pip install -r requirements.txt
      - run: PYTHONPATH=. pytest
        env:
          DATABASE_URL: postgresql://ytmood:ytmoodpw@localhost:5432/ytmood
```

## 보안
- DB/Redis 비밀번호, API 키는 코드에 하드코딩하지 않고 환경변수로만 관리
- `ADMIN_API_KEY`를 설정하지 않으면 관리자 엔드포인트는 Admin 플랜 키로만 접근 가능
