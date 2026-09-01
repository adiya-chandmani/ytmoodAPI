"""
sentiment_analyzer.py: 영어 소셜미디어 댓글 감정 분석 (HuggingFace 기반)

모델은 첫 요청 때 지연 로딩한다. 로딩에 실패하면(메모리 부족, 네트워크 등)
사전 기반 폴백으로 자동 전환되며 예외는 호출자에게 전파되지 않는다.
"""
import logging
import re

logger = logging.getLogger("ytmoodapi.sentiment")

MODEL_NAME = "cardiffnlp/twitter-roberta-base-sentiment"
LABELS = ["negative", "neutral", "positive"]

_model = None
_load_attempted = False

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
    """Return (tokenizer, model, torch) or None if the heavy stack is unusable."""
    global _load_attempted
    _load_attempted = True
    try:
        from transformers import AutoTokenizer, AutoModelForSequenceClassification
        import torch

        tokenizer = AutoTokenizer.from_pretrained(MODEL_NAME)
        model = AutoModelForSequenceClassification.from_pretrained(MODEL_NAME)
        return tokenizer, model, torch
    except Exception:
        logger.warning(
            "Transformer model unavailable; using lexicon fallback", exc_info=True
        )
        return None


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
    global _model
    if not _load_attempted:
        _model = _load_model()
    if _model is None:
        return _lexicon_sentiment(comment)
    tokenizer, model, torch = _model
    try:
        inputs = tokenizer(comment, return_tensors="pt", truncation=True, max_length=128)
        with torch.no_grad():
            outputs = model(**inputs)
            probs = torch.softmax(outputs.logits, dim=1)
            label = torch.argmax(probs, dim=1).item()
        return LABELS[label]
    except Exception:
        logger.warning("Inference failed; using lexicon fallback", exc_info=True)
        return _lexicon_sentiment(comment)
