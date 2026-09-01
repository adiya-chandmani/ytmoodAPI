import sys
import time
import types

import pytest

import sentiment_analyzer
from sentiment_analyzer import LABELS, _lexicon_sentiment, analyze_sentiment


@pytest.fixture
def unloaded(monkeypatch):
    """모델 적재 상태를 초기화해 로딩 경로를 매번 처음부터 태운다."""
    monkeypatch.setattr(sentiment_analyzer, "_tokenizer", None)
    monkeypatch.setattr(sentiment_analyzer, "_model", None)
    monkeypatch.setattr(sentiment_analyzer, "_torch", None)
    monkeypatch.setattr(sentiment_analyzer, "_model_load_failed", False)
    return sentiment_analyzer


def _fake_transformers(delay=0.0):
    """from_pretrained가 delay초 걸리는 가짜 transformers 모듈."""
    module = types.ModuleType("transformers")

    class _Slow:
        @staticmethod
        def from_pretrained(name):
            time.sleep(delay)
            return object()

    module.AutoTokenizer = _Slow
    module.AutoModelForSequenceClassification = _Slow
    return module


def _stub_heavy_deps(monkeypatch, transformers_module):
    """transformers와 torch를 함께 갈아끼운다. 테스트 환경에 torch가 없어도 된다."""
    monkeypatch.setitem(sys.modules, "transformers", transformers_module)
    monkeypatch.setitem(sys.modules, "torch", types.ModuleType("torch"))


@pytest.mark.parametrize(
    "text",
    ["정말 좋아요! 최고!", "진짜 별로고 최악이야", "음... 그냥 그렇네요", ""],
)
def test_analyze_sentiment_always_returns_a_valid_label(text):
    # 모델이 로드됐든 폴백이든 유효한 라벨을 돌려줘야 하고 예외를 던지면 안 된다.
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


def test_slow_model_load_gives_up_and_falls_back(unloaded, monkeypatch):
    # 배포 환경에서 실제로 터진 문제: 모델 다운로드가 게이트웨이 타임아웃보다
    # 오래 걸리는데 예외가 아니라 지연이라 폴백이 발동하지 않았다.
    _stub_heavy_deps(monkeypatch, _fake_transformers(delay=30))
    monkeypatch.setattr(sentiment_analyzer, "MODEL_LOAD_TIMEOUT_SECONDS", 0.3)

    start = time.monotonic()
    result = analyze_sentiment("This video is awesome, I love it!")
    elapsed = time.monotonic() - start

    assert result == "positive"  # 폴백 결과
    assert elapsed < 5, f"제한 시간을 넘겨 {elapsed:.1f}초 대기했다"
    assert sentiment_analyzer._model_load_failed is True


def test_second_call_after_timeout_is_immediate(unloaded, monkeypatch):
    _stub_heavy_deps(monkeypatch, _fake_transformers(delay=30))
    monkeypatch.setattr(sentiment_analyzer, "MODEL_LOAD_TIMEOUT_SECONDS", 0.3)

    analyze_sentiment("first call pays the timeout")
    start = time.monotonic()
    analyze_sentiment("second call must not wait again")
    # 실패를 기억하지 못하면 매 요청마다 처음부터 다시 받으려 한다
    assert time.monotonic() - start < 0.1


def test_load_failure_falls_back(unloaded, monkeypatch):
    broken = types.ModuleType("transformers")  # 필요한 이름이 없어 ImportError
    monkeypatch.setitem(sys.modules, "transformers", broken)
    assert analyze_sentiment("This is awesome") == "positive"
    assert sentiment_analyzer._model_load_failed is True


def test_model_is_used_when_it_loads_in_time(unloaded, monkeypatch):
    _stub_heavy_deps(monkeypatch, _fake_transformers(delay=0))
    monkeypatch.setattr(sentiment_analyzer, "MODEL_LOAD_TIMEOUT_SECONDS", 5)

    analyze_sentiment("warm up the loader")
    assert sentiment_analyzer._model_load_failed is False
    assert sentiment_analyzer._model is not None
    # 가짜 모델이라 추론은 실패하고 폴백으로 내려가지만, 예외는 새어나가지 않는다
    assert analyze_sentiment("This is awesome") in LABELS


def test_concurrent_first_calls_load_once(unloaded, monkeypatch):
    import threading

    calls = []

    module = types.ModuleType("transformers")

    class _Counted:
        @staticmethod
        def from_pretrained(name):
            calls.append(name)
            time.sleep(0.05)
            return object()

    module.AutoTokenizer = _Counted
    module.AutoModelForSequenceClassification = _Counted
    _stub_heavy_deps(monkeypatch, module)
    monkeypatch.setattr(sentiment_analyzer, "MODEL_LOAD_TIMEOUT_SECONDS", 5)

    threads = [
        threading.Thread(target=analyze_sentiment, args=("hello",)) for _ in range(8)
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    # 락이 없으면 스레드마다 다시 내려받는다. tokenizer + model = 2회가 정상.
    assert len(calls) == 2
