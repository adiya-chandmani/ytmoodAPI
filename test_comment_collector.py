import os
import pytest
from comment_collector import collect_comments

def test_collect_comments_success():
    api_key = os.getenv("YOUTUBE_API_KEY")
    if not api_key:
        pytest.skip("YOUTUBE_API_KEY 환경변수 필요")
    video_id = "dQw4w9WgXcQ"  # 예시 영상 ID
    comments = collect_comments(video_id, api_key, max_results=5)
    assert isinstance(comments, list)
    assert len(comments) <= 5

def test_collect_comments_invalid_key():
    video_id = "dQw4w9WgXcQ"
    comments = collect_comments(video_id, "invalid_key", max_results=5)
    assert comments == [] 