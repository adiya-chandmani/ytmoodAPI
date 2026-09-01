"""
sentiment_analyzer.py: 영어 소셜미디어 댓글 감정 분석 (HuggingFace 기반)

모델은 첫 요청 때 지연 로딩한다. 로딩이 실패하거나 제한 시간을 넘기면 사전 기반
폴백으로 자동 전환되며, 예외도 지연도 호출자에게 전파되지 않는다.
"""
import logging
import os
import re
import threading

logger = logging.getLogger("ytmoodapi.sentiment")

MODEL_NAME = "cardiffnlp/twitter-roberta-base-sentiment"
LABELS = ["negative", "neutral", "positive"]

# 무료/저사양 호스팅에서는 500MB짜리 모델 다운로드가 게이트웨이 타임아웃보다
# 오래 걸린다. 예외가 아니라 '너무 느림'도 실패로 취급해야 폴백이 실제로 동작한다.
MODEL_LOAD_TIMEOUT_SECONDS = float(os.getenv("SENTIMENT_MODEL_TIMEOUT_SECONDS", "8"))

_tokenizer = None
_model = None
_torch = None
_model_load_failed = False
_load_lock = threading.Lock()

POSITIVE_TERMS = {
    "good", "great", "love", "loved", "lovely", "awesome", "amazing", "best",
    "excellent", "perfect", "nice", "happy", "beautiful", "wonderful", "fun",
    "thanks", "thank", "helpful", "cool", "brilliant", "enjoyed", "recommend",
    # 기존 테스트가 한국어 문장을 쓰므로 최소한의 한국어 항목도 포함
    "좋아", "최고", "감사", "훌륭",
}
NEGATIVE_TERMS = {
    "bad", "worst", "hate", "hated", "awful", "terrible", "boring", "trash",
    "garbage", "stupid", "useless", "waste", "disappointing", "disappointed",
    "poor", "annoying", "cringe", "sucks", "sucked", "horrible",
    "별로", "최악", "싫어", "짜증",
}

_WORD_RE = re.compile(r"[a-z0-9']+")


def _load_model():
    """
    모델을 한 번만 적재한다. 제한 시간 안에 끝나지 않으면 이 프로세스가 사는 동안
    다시 시도하지 않고 폴백만 쓴다.
    """
    global _tokenizer, _model, _torch, _model_load_failed

    if _model is not None or _model_load_failed:
        return

    with _load_lock:
        # 락을 기다리는 사이 다른 스레드가 끝냈거나 실패 처리했을 수 있다
        if _model is not None or _model_load_failed:
            return

        result = {}

        def _attempt():
            try:
                from transformers import (
                    AutoModelForSequenceClassification,
                    AutoTokenizer,
                )
                import torch

                result["tokenizer"] = AutoTokenizer.from_pretrained(MODEL_NAME)
                result["model"] = AutoModelForSequenceClassification.from_pretrained(
                    MODEL_NAME
                )
                result["torch"] = torch
            except Exception as exc:
                result["error"] = exc

        worker = threading.Thread(target=_attempt, daemon=True)
        worker.start()
        worker.join(timeout=MODEL_LOAD_TIMEOUT_SECONDS)

        if worker.is_alive() or "model" not in result:
            # ponytail: 시간 초과 시 백그라운드 스레드는 계속 내려받는다. 데몬이라
            # 프로세스 종료는 막지 않지만 512MB 인스턴스에서는 그 다운로드 자체가
            # 메모리를 밀어낼 수 있다. 그게 문제가 되면 이미지 빌드 때 모델을
            # 미리 받아두거나 아예 로딩을 끄는 편이 낫다.
            _model_load_failed = True
            if "error" in result:
                logger.warning(
                    "Sentiment model failed to load (%s); falling back to "
                    "lexicon-based analysis.",
                    result["error"],
                )
            else:
                logger.warning(
                    "Sentiment model did not load within %ss; falling back to "
                    "lexicon-based analysis.",
                    MODEL_LOAD_TIMEOUT_SECONDS,
                )
            return

        _tokenizer = result["tokenizer"]
        _model = result["model"]
        _torch = result["torch"]
        logger.info("Loaded sentiment model %s", MODEL_NAME)


def _lexicon_sentiment(comment: str) -> str:
    lowered = comment.lower()
    words = set(_WORD_RE.findall(lowered))
    # ASCII terms match whole words; non-ASCII (Korean) terms match as substrings
    # because Korean particles attach directly to the stem.
    def hits(terms):
        return sum(
            1 for t in terms if (t in words if t.isascii() else t in lowered)
        )

    score = hits(POSITIVE_TERMS) - hits(NEGATIVE_TERMS)
    if score > 0:
        return "positive"
    if score < 0:
        return "negative"
    return "neutral"


def analyze_sentiment(comment: str) -> str:
    _load_model()
    if _model is None:
        return _lexicon_sentiment(comment)
    try:
        inputs = _tokenizer(
            comment, return_tensors="pt", truncation=True, max_length=128
        )
        with _torch.no_grad():
            outputs = _model(**inputs)
            probs = _torch.softmax(outputs.logits, dim=1)
            label = _torch.argmax(probs, dim=1).item()
        return LABELS[label]
    except Exception as exc:
        logger.warning("Inference failed (%s); using lexicon fallback", exc)
        return _lexicon_sentiment(comment)
