import pytest

import models
from db import Base, SessionLocal, engine


@pytest.fixture(scope="module", autouse=True)
def setup_db():
    # 예전에는 teardown에서 drop_all을 호출했다. DATABASE_URL이 운영 DB를 가리킨
    # 채로 pytest를 돌리면 테이블을 전부 날려버리므로 테이블은 만들기만 하고,
    # 각 테스트가 자기 행만 지운다.
    Base.metadata.create_all(bind=engine)
    yield


def test_create_and_query_user():
    db = SessionLocal()
    try:
        # seed_plans가 명시 id로 심어 plans_id_seq가 뒤처져 있으므로, id 없는
        # Plan insert는 기존 행과 충돌한다. 시더가 만든 플랜을 그대로 쓴다.
        models.seed_plans(db)
        plan = db.query(models.Plan).filter_by(name="Free").one()

        user = models.User(username="test_db_user", plan_id=plan.id)
        db.add(user)
        db.commit()
        db.refresh(user)

        queried = db.query(models.User).filter_by(username="test_db_user").first()
        assert queried is not None
        assert queried.plan_id == plan.id
    finally:
        db.query(models.User).filter_by(username="test_db_user").delete()
        db.commit()
        db.close()
