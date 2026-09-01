"""
keyword_extractor.py: 키워드 추출 모듈 (한국어/영어)
"""
import re
from collections import Counter
from typing import List

TOP_N = 5

ENGLISH_STOPWORDS = {
    "the", "and", "is", "are", "was", "were", "be", "to", "of", "in", "on",
    "for", "with", "a", "an", "it", "this", "that", "at", "as", "by", "from",
    "but", "or", "so", "if", "not", "you", "i", "me", "my", "we", "us", "our",
    "your", "he", "she", "they", "them", "their", "his", "her", "do", "does",
    "did", "have", "has", "had", "will", "would", "can", "could", "should",
    "about", "just", "very", "all", "too", "out", "up", "down", "more", "no",
    "yes", "than", "then", "now", "how", "what", "when", "where", "who",
    "which", "why",
}

KOREAN_STOPWORDS = {
    "그리고", "그런데", "하지만", "그래서", "너무", "정말", "진짜", "그냥",
    "이건", "저건", "그건", "이거", "저거", "그거", "여기", "저기", "거기",
    "제가", "저는", "나는", "내가", "우리", "당신", "근데", "역시", "다시",
    "많이", "조금", "약간", "아주", "매우", "완전", "계속", "지금", "이제",
}

STOPWORDS = ENGLISH_STOPWORDS | KOREAN_STOPWORDS

# \w 는 유니코드 기본이라 한글도 잡는다. 숫자만으로 된 토큰은 뒤에서 걸러낸다.
_WORD_RE = re.compile(r"\w+", re.UNICODE)


def extract_keywords(comments: List[str], top_n: int = TOP_N) -> List[str]:
    """
    댓글 리스트에서 주요 키워드 추출 (빈도순, 2글자 이상, 불용어/숫자 제외).
    최대 top_n개를 반환한다.
    """
    words = []
    for comment in comments:
        for word in _WORD_RE.findall(comment.lower()):
            if len(word) < 2 or word.isdigit() or word in STOPWORDS:
                continue
            words.append(word)
    return [w for w, _ in Counter(words).most_common(top_n)]
