import pytest
from db import SessionLocal, Base, engine
import models

@pytest.fixture(scope="module", autouse=True)
def setup_db():
    Base.metadata.create_all(bind=engine)
    yield
    Base.metadata.drop_all(bind=engine)

def test_create_and_query_user():
    db = SessionLocal()
    plan = models.Plan(name="Free")
    db.add(plan)
    db.commit()
    db.refresh(plan)
    user = models.User(username="testuser", plan_id=plan.id)
    db.add(user)
    db.commit()
    db.refresh(user)
    queried = db.query(models.User).filter_by(username="testuser").first()
    assert queried is not None
    assert queried.plan_id == plan.id
    db.delete(user)
    db.delete(plan)
    db.commit()
    db.close() 