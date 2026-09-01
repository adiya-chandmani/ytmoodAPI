from main import summarize


def test_summary_format():
    comments = [
        "진짜 잘했어요!", "계속 보고 싶어요!", "내용이 너무 지루해요",
        "이건 좀 별로네요", "목소리 최고", "사랑해요",
    ]
    result = summarize(comments)
    assert set(result) == {
        "summary", "keywords", "highlighted_comments", "profanity_count",
    }
    assert set(result["summary"]) == {"positive", "neutral", "negative"}
    assert all(isinstance(v, int) for v in result["summary"].values())
    assert isinstance(result["keywords"], list)
    assert isinstance(result["highlighted_comments"]["positive"], list)
    assert isinstance(result["highlighted_comments"]["negative"], list)
    assert isinstance(result["profanity_count"], int)


def test_summary_handles_no_comments():
    # 댓글이 0개여도 ZeroDivisionError 없이 동작해야 한다.
    result = summarize([])
    assert result["summary"] == {"positive": 0, "neutral": 0, "negative": 0}
    assert result["keywords"] == []
    assert result["profanity_count"] == 0


def test_highlights_come_from_their_own_bucket():
    result = summarize(["awesome video", "terrible video", "a video"])
    for comment in result["highlighted_comments"]["positive"]:
        assert comment in ["awesome video", "terrible video", "a video"]
    assert len(result["highlighted_comments"]["positive"]) <= 2
    assert len(result["highlighted_comments"]["negative"]) <= 2
