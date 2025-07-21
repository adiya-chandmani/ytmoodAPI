from profanity_detector import detect_profanity

def test_no_profanity():
    assert detect_profanity("이 영상 정말 좋아요") is False

def test_profanity_korean():
    assert detect_profanity("씨발 뭐야") is True

def test_profanity_english():
    assert detect_profanity("this is shit") is True 