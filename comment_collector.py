"""
comment_collector.py: 유튜브 댓글 수집 모듈
"""
import requests
from typing import List

def collect_comments(video_id: str, api_key: str, max_results: int = 50) -> List[str]:
    """
    YouTube 영상 ID와 API 키로 댓글 리스트를 수집한다.
    Args:
        video_id (str): 유튜브 영상 ID
        api_key (str): YouTube Data API 키
        max_results (int): 최대 댓글 수
    Returns:
        List[str]: 댓글 텍스트 리스트
    """
    url = "https://www.googleapis.com/youtube/v3/commentThreads"
    params = {
        "part": "snippet",
        "videoId": video_id,
        "key": api_key,
        "maxResults": max_results
    }
    comments = []
    try:
        resp = requests.get(url, params=params, timeout=10)
        resp.raise_for_status()
        data = resp.json()
        for item in data.get("items", []):
            top_comment = item["snippet"]["topLevelComment"]["snippet"]["textDisplay"]
            comments.append(top_comment)
    except Exception as e:
        # TODO: 로깅 및 예외 처리
        pass
    return comments 