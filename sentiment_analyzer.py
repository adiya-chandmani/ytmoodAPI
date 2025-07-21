"""
sentiment_analyzer.py: 영어 소셜미디어 댓글 감정 분석 (HuggingFace 기반)
"""
from transformers import AutoTokenizer, AutoModelForSequenceClassification
import torch

MODEL_NAME = "cardiffnlp/twitter-roberta-base-sentiment"
tokenizer = AutoTokenizer.from_pretrained(MODEL_NAME)
model = AutoModelForSequenceClassification.from_pretrained(MODEL_NAME)

LABELS = ["negative", "neutral", "positive"]

def analyze_sentiment(comment: str) -> str:
    inputs = tokenizer(comment, return_tensors="pt", truncation=True, max_length=128)
    with torch.no_grad():
        outputs = model(**inputs)
        logits = outputs.logits
        probs = torch.softmax(logits, dim=1)
        label = torch.argmax(probs, dim=1).item()
    return LABELS[label]