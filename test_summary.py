from main import summarize

def test_summary_format():
    comments = [
        "진짜 잘했어요!", "계속 보고 싶어요!", "내용이 너무 지루해요", "이건 좀 별로네요", "목소리 최고", "사랑해요"
    ]
    result = summarize(comments)
    assert "summary" in result
    assert "keywords" in result
    assert "highlighted_comments" in result
    assert set(result["summary"].keys()) == {"positive", "neutral", "negative"}
    assert isinstance(result["keywords"], list)
    assert "positive" in result["highlighted_comments"]
    assert "negative" in result["highlighted_comments"]
    assert isinstance(result["highlighted_comments"]["positive"], list)
    assert isinstance(result["highlighted_comments"]["negative"], list) 