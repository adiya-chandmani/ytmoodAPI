from sqlalchemy import Column, Integer, String, ForeignKey, DateTime, Text
from sqlalchemy.orm import relationship
from db import Base
import datetime

class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True, index=True)
    username = Column(String, unique=True, index=True)
    plan_id = Column(Integer, ForeignKey("plans.id"))
    api_keys = relationship("ApiKey", back_populates="user")
    plan = relationship("Plan", back_populates="users")

class Plan(Base):
    __tablename__ = "plans"
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, unique=True, index=True)
    users = relationship("User", back_populates="plan")

class ApiKey(Base):
    __tablename__ = "api_keys"
    id = Column(Integer, primary_key=True, index=True)
    key = Column(String, unique=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"))
    user = relationship("User", back_populates="api_keys")

class AnalysisResult(Base):
    __tablename__ = "analysis_results"
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"))
    video_id = Column(String, index=True)
    result_json = Column(Text)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)

def seed_plans(db):
    plans = [
        Plan(id=1, name="Free"),
        Plan(id=2, name="Pro"),
        Plan(id=3, name="Business"),
        Plan(id=99, name="Admin")
    ]
    for plan in plans:
        if not db.query(Plan).filter_by(id=plan.id).first():
            db.add(plan)
    db.commit()

# 사용 예시 (컨테이너 내부 python 셸에서):
# from db import SessionLocal
# from models import seed_plans
# db = SessionLocal()
# seed_plans(db)
# db.close() 