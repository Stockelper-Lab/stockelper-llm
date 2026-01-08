import asyncio
import os
from dotenv import load_dotenv
import json
from dotenv import load_dotenv
from pprint import pprint
from langchain_core.tools import BaseTool
from typing import Type, Optional, Dict, Any
from pydantic import BaseModel, Field, PrivateAttr
from youtube_transcript_api import YouTubeTranscriptApi
from urllib.parse import urlparse, parse_qs
from googleapiclient.discovery import build
from langchain_core.callbacks import AsyncCallbackManagerForToolRun, CallbackManagerForToolRun
from langchain_core.runnables import RunnableConfig
from datetime import datetime


class YouTubeSearchInput(BaseModel):
    query: str = Field(description="Keywords or topics to search for")
    max_results: int = Field(default=1, description="Maximum number of videos to search for")


class YouTubeSearchTool(BaseTool):    
    name: str = "youtube_transcript_search"
    description: str = "A tool to search for stock/investment related videos on YouTube and extract their transcripts."
    args_schema: Type[BaseModel] = YouTubeSearchInput
    return_direct: bool = False

    async def _get_transcript(self, video_id: str) -> str:
        """YouTube 동영상의 자막을 추출"""
        try:
            transcript = await asyncio.get_event_loop().run_in_executor(
                None,
                lambda: YouTubeTranscriptApi.get_transcript(video_id, languages=['ko', 'en'])
            )
            # 자막 텍스트를 1000자로 제한
            full_text = "\n".join([item['text'] for item in transcript])
            return full_text[:1000] + ("..." if len(full_text) > 1000 else "")
        except Exception as e:
            return f"자막 없음: {str(e)}"

    def _extract_video_id(self, url: str) -> str:
        """URL에서 video ID 추출"""
        if 'youtu.be' in url:
            return url.split('/')[-1]
        parsed_url = urlparse(url)
        return parse_qs(parsed_url.query)['v'][0]

    def _run(
        self,
        query: str,
        max_results: int = 1,
        config: RunnableConfig = None,
        run_manager: Optional[CallbackManagerForToolRun] = None,
    ) -> Dict[str, Any]:
        """동기 메서드는 비동기 메서드를 실행"""
        return asyncio.run(self._arun(query, max_results, config, run_manager))

    async def _arun(
        self,
        query: str,
        max_results: int = 1,
        config: RunnableConfig = None,
        run_manager: Optional[AsyncCallbackManagerForToolRun] = None,
    ) -> Dict[str, Any]:
        """메인 비동기 실행 메서드"""
        try:
            load_dotenv(override=True)
            if not os.getenv("YOUTUBE_API_KEY"):
                return {"error": "YOUTUBE_API_KEY 환경변수가 설정되어 있지 않습니다.", "query": query}
            # YouTube API 클라이언트 생성과 검색 실행
            youtube_search = await asyncio.get_event_loop().run_in_executor(
                None,
                lambda: build('youtube', 'v3', developerKey=os.environ["YOUTUBE_API_KEY"]).search().list(
                    q=query,
                    part='id,snippet',
                    maxResults=max_results,
                    type='video',
                    order='relevance',
                    relevanceLanguage='ko'
                ).execute()
            )
            
            # 검색 결과를 순차적으로 처리
            results = []
            all_transcripts = []  # 모든 자막을 저장할 리스트
            
            for item in youtube_search.get('items', []):
                video_id = item['id']['videoId']
                video_info = {
                    'title': item['snippet']['title'],
                    'channel': item['snippet']['channelTitle'],
                    'description': item['snippet']['description'],
                    'url': f"https://www.youtube.com/watch?v={video_id}",
                }
                
                # 자막 가져오기 (순차적으로 실행)
                transcript = await self._get_transcript(video_id)
                video_info['transcript'] = transcript
                results.append(video_info)

            return results
            
        except Exception as e:
            return {
                'error': str(e),
                'query': query
            }
