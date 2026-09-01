import os
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base

DATABASE_URL = os.getenv("DATABASE_URL")
if not DATABASE_URL:
    POSTGRES_USER = os.getenv("POSTGRES_USER", "ytmood")
    POSTGRES_PASSWORD = os.getenv("POSTGRES_PASSWORD", "ytmoodpw")
    POSTGRES_DB = os.getenv("POSTGRES_DB", "ytmood")
    POSTGRES_HOST = os.getenv("POSTGRES_HOST", "localhost")
    POSTGRES_PORT = os.getenv("POSTGRES_PORT", "5432")
    DATABASE_URL = f"postgresql://{POSTGRES_USER}:{POSTGRES_PASSWORD}@{POSTGRES_HOST}:{POSTGRES_PORT}/{POSTGRES_DB}"

# Render/Heroku hand out postgres:// URLs; SQLAlchemy 2.x only accepts postgresql://
if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)

engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


def get_db():
    """FastAPI 의존성: 요청이 끝나면 예외 여부와 무관하게 세션을 닫는다."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
