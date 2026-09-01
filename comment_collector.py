"""
comment_collector.py: 유튜브 댓글 수집 모듈
"""
import logging
from typing import List

import requests

logger = logging.getLogger("ytmoodapi.comment_collector")

API_URL = "https://www.googleapis.com/youtube/v3/commentThreads"


class CommentCollectionError(RuntimeError):
    """댓글을 가져오지 못했다. '댓글이 0개'와 구분하기 위한 예외."""


def collect_comments(video_id: str, api_key: str, max_results: int = 50) -> List[str]:
    """
    YouTube 영상 ID와 API 키로 댓글 리스트를 수집한다.

    Args:
        video_id (str): 유튜브 영상 ID
        api_key (str): YouTube Data API 키
        max_results (int): 최대 댓글 수
    Returns:
        List[str]: 댓글 텍스트 리스트. 댓글이 없으면 빈 리스트.
    Raises:
        CommentCollectionError: 키가 잘못됐거나 할당량 초과, 네트워크 실패 등
            수집 자체가 실패한 경우. 빈 결과와 구분하기 위해 삼키지 않는다.
    """
    params = {
        "part": "snippet",
        "videoId": video_id,
        "key": api_key,
        "maxResults": max_results,
    }
    try:
        resp = requests.get(API_URL, params=params, timeout=10)
    except requests.RequestException as exc:
        logger.warning("YouTube API 요청 실패: %s", exc)
        raise CommentCollectionError("YouTube API에 접속하지 못했습니다") from exc

    if resp.status_code != 200:
        detail = _error_reason(resp)
        logger.warning("YouTube API %s: %s", resp.status_code, detail)
        raise CommentCollectionError(f"YouTube API 오류({resp.status_code}): {detail}")

    try:
        items = resp.json().get("items", [])
    except ValueError as exc:
        raise CommentCollectionError("YouTube 응답을 해석하지 못했습니다") from exc

    comments = []
    for item in items:
        try:
            comments.append(
                item["snippet"]["topLevelComment"]["snippet"]["textDisplay"]
            )
        except (KeyError, TypeError):
            # 개별 항목의 형태가 예상과 다르면 그 항목만 건너뛴다
            logger.debug("예상과 다른 댓글 항목을 건너뜀")
    return comments


def _error_reason(resp) -> str:
    try:
        return resp.json()["error"]["message"]
    except Exception:
        return resp.text[:200] or "알 수 없는 오류"
