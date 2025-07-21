"""
keyword_extractor.py: 영어 키워드 추출 모듈
"""
from typing import List
from collections import Counter
import re

def extract_keywords(comments: List[str]) -> List[str]:
    """
    영어 댓글 리스트에서 주요 키워드 추출 (빈도순, 2글자 이상, 불용어 제외)
    """
    stopwords = set([
        "the", "and", "is", "are", "was", "were", "be", "to", "of", "in", "on", "for", "with", "a", "an", "it", "this", "that", "at", "as", "by", "from", "but", "or", "so", "if", "not", "you", "i", "me", "my", "we", "us", "our", "your", "he", "she", "they", "them", "their", "his", "her", "do", "does", "did", "have", "has", "had", "will", "would", "can", "could", "should", "about", "just", "very", "all", "too", "out", "up", "down", "more", "no", "yes", "than", "then", "now", "how", "what", "when", "where", "who", "which", "why"
    ])
    words = []
    for comment in comments:
        for word in re.findall(r"[a-zA-Z]+", comment.lower()):
            if len(word) >= 2 and word not in stopwords:
                words.append(word)
    return [w for w, _ in Counter(words).most_common(5)] 