"""
profanity_detector.py: 욕설 감지 모듈
"""

# 간단한 비속어 목록. 부분 문자열로 검사하므로 조사가 붙어도 잡힌다.
PROFANITIES = [
    "씨발", "시발", "ㅅㅂ", "병신", "ㅂㅅ", "지랄", "좆", "개새끼", "새끼",
    "fuck", "shit", "bitch", "asshole", "bastard",
]


def detect_profanity(comment: str) -> bool:
    """
    댓글 내 욕설 포함 여부 반환 (간단한 비속어 리스트 기반)
    """
    lowered = comment.lower()
    return any(word in lowered for word in PROFANITIES)
