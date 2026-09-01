from keyword_extractor import TOP_N, extract_keywords


def test_extract_keywords_korean():
    comments = ["목소리 너무 좋아요", "편집 최고", "목소리 편집 사랑해요"]
    keywords = extract_keywords(comments)
    # 두 번씩 등장한 단어가 가장 앞에 온다
    assert keywords[:2] == ["목소리", "편집"]
    # "너무"는 불용어라 빠진다
    assert "너무" not in keywords
    assert len(keywords) <= TOP_N


def test_extract_keywords_english():
    comments = ["great video and the editing is great", "editing rocks"]
    keywords = extract_keywords(comments)
    assert keywords[:2] == ["great", "editing"]
    assert "the" not in keywords  # 불용어
    assert "is" not in keywords


def test_extract_keywords_empty():
    assert extract_keywords([]) == []
