import os

import pytest
import requests

from comment_collector import CommentCollectionError, collect_comments


class _FakeResponse:
    def __init__(self, status_code, payload=None, text=""):
        self.status_code = status_code
        self._payload = payload
        self.text = text

    def json(self):
        if self._payload is None:
            raise ValueError("no json")
        return self._payload


def _comment_item(text):
    return {"snippet": {"topLevelComment": {"snippet": {"textDisplay": text}}}}


def test_collect_comments_success():
    api_key = os.getenv("YOUTUBE_API_KEY")
    if not api_key:
        pytest.skip("YOUTUBE_API_KEY 환경변수 필요")
    comments = collect_comments("dQw4w9WgXcQ", api_key, max_results=5)
    assert isinstance(comments, list)
    assert len(comments) <= 5


def test_collect_comments_parses_items(monkeypatch):
    payload = {"items": [_comment_item("첫 댓글"), _comment_item("두 번째")]}
    monkeypatch.setattr(
        requests, "get", lambda *a, **k: _FakeResponse(200, payload)
    )
    assert collect_comments("vid", "key") == ["첫 댓글", "두 번째"]


def test_collect_comments_empty_is_not_an_error(monkeypatch):
    monkeypatch.setattr(
        requests, "get", lambda *a, **k: _FakeResponse(200, {"items": []})
    )
    assert collect_comments("vid", "key") == []


def test_collect_comments_invalid_key_raises(monkeypatch):
    # 예전에는 빈 리스트를 반환해 '댓글 0개'와 구분할 수 없었다.
    payload = {"error": {"message": "API key not valid"}}
    monkeypatch.setattr(
        requests, "get", lambda *a, **k: _FakeResponse(400, payload)
    )
    with pytest.raises(CommentCollectionError, match="API key not valid"):
        collect_comments("vid", "invalid_key")


def test_collect_comments_network_failure_raises(monkeypatch):
    def _boom(*a, **k):
        raise requests.ConnectionError("dns failure")

    monkeypatch.setattr(requests, "get", _boom)
    with pytest.raises(CommentCollectionError):
        collect_comments("vid", "key")
