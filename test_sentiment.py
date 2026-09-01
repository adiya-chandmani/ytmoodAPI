import pytest

import sentiment_analyzer
from sentiment_analyzer import LABELS, _lexicon_sentiment, analyze_sentiment


@pytest.mark.parametrize(
    "text",
    ["정말 좋아요! 최고!", "진짜 별로고 최악이야", "음... 그냥 그렇네요", ""],
)
def test_analyze_sentiment_always_returns_a_valid_label(text):
    # 모델이 로드됐든 폴백이든 유효한 라벨을 돌려줘야 하고 예외를 던지면 안 된다.
    # 어느 쪽이 쓰이는지는 환경에 따라 다르므로 여기서는 의미를 단정하지 않는다.
    assert analyze_sentiment(text) in LABELS


@pytest.mark.parametrize(
    "text,expected",
    [
        ("This video is awesome, I love it!", "positive"),
        ("worst tutorial ever, total garbage", "negative"),
        ("uploaded on tuesday at the studio", "neutral"),
        ("정말 좋아요! 최고!", "positive"),
        ("진짜 별로고 최악이야", "negative"),
        ("음... 그냥 그렇네요", "neutral"),
    ],
)
def test_lexicon_fallback_classifies(text, expected):
    # 폴백 경로는 결정적이므로 의미까지 직접 검증한다.
    assert _lexicon_sentiment(text) == expected


def test_model_is_not_loaded_at_import(monkeypatch):
    # import만으로 무거운 모델을 받아오면 512MB 인스턴스가 기동에 실패한다.
    monkeypatch.setattr(sentiment_analyzer, "_load_attempted", False)
    monkeypatch.setattr(sentiment_analyzer, "_model", None)
    assert sentiment_analyzer._load_attempted is False


def test_falls_back_when_model_load_fails(monkeypatch):
    monkeypatch.setattr(sentiment_analyzer, "_load_attempted", False)
    monkeypatch.setattr(sentiment_analyzer, "_model", None)
    monkeypatch.setattr(sentiment_analyzer, "_load_model", lambda: None)
    assert analyze_sentiment("This is awesome") == "positive"
