from sentiment_analyzer import analyze_sentiment

def test_positive():
    assert analyze_sentiment("정말 좋아요! 최고!") == "positive"

def test_negative():
    assert analyze_sentiment("진짜 별로고 최악이야") == "negative"

def test_neutral():
    assert analyze_sentiment("음... 그냥 그렇네요") == "neutral" 