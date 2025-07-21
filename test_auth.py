import pytest
from auth import check_usage, get_plan

FREE_KEY = "free_key"
PRO_KEY = "pro_key"
BIZ_KEY = "biz_key"


def test_get_plan():
    assert get_plan(FREE_KEY) == "Free"
    assert get_plan(PRO_KEY) == "Pro"
    assert get_plan(BIZ_KEY) == "Business"
    assert get_plan("unknown") == "Free"

with pytest.raises(Exception):
        get_plan("unknown")

def test_check_usage_free():
    for _ in range(100):
        check_usage(FREE_KEY)
    with pytest.raises(Exception):
        check_usage(FREE_KEY)

def test_check_usage_pro():
    for _ in range(30000):
        check_usage(PRO_KEY)
    with pytest.raises(Exception):
        check_usage(PRO_KEY) 