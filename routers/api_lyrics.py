# routers/api_lyrics.py

from fastapi import APIRouter
from pydantic import BaseModel
import threading  # 🌟 추가

from services.melon import fetch_lyrics_melon

router = APIRouter()

crawl_lock_sync = threading.Lock()

class LyricsReq(BaseModel):
    title: str
    artist: str | None = ""

@router.post("/api/lyrics/fetch")
def fetch_lyrics(req: LyricsReq):
    # 🌟 with 문으로 락을 걸어서 동시 실행 방지
    with crawl_lock_sync:
        lyrics = fetch_lyrics_melon(req.title, req.artist or "")
        return {"lyrics": lyrics}