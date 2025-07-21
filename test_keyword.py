from keyword_extractor import extract_keywords

def test_extract_keywords():
    comments = ["목소리 너무 좋아요", "편집 최고", "목소리 편집 사랑해요"]
    keywords = extract_keywords(comments)
    assert "목소리" in keywords
    assert "편집" in keywords
    assert len(keywords) == 3 