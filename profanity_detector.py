"""
profanity_detector.py: 욕설 감지 모듈
"""
from typing import List

def detect_profanity(comment: str) -> bool:
    """
    댓글 내 욕설 포함 여부 반환 (간단한 비속어 리스트 기반)
    """
    profanities = ["욕1", "욕2", "씨발", "ㅅㅂ", "fuck", "shit"]
    return any(word in comment for word in profanities) 