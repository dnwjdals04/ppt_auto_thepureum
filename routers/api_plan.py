# routers/api_plan.py

from fastapi import APIRouter, Request, Form, HTTPException
from fastapi.responses import RedirectResponse
from fastapi.concurrency import run_in_threadpool  # 🌟 추가: 서버 멈춤 방지용
import asyncio  # 🌟 추가: 연타 방지용 Lock

import datetime
from pathlib import Path

from services import conti
from services.melon import fetch_lyrics_batch_melon

LYRICS_DIR = Path(__file__).resolve().parent.parent / "lyrics"

router = APIRouter()

crawl_lock = asyncio.Lock()

def _store(request: Request):
    return request.app.state.store


@router.post("/api/plan/init")
async def plan_init(
    request: Request,
    praise_count: int = Form(3),  # 콘티가 없을 때의 곡 수 (입력칸은 없앰)
    prayer: str = Form("기도 | "),
    sermon_title: str = Form(""),
    sermon_phrases_raw: str = Form(""),
    include_offering: int = Form(0),
    include_closing: int = Form(0),
    service_date: str = Form(""),
    conti_raw: str = Form(""),
):
    if not (1 <= praise_count <= 20):
        raise HTTPException(status_code=400, detail="praise_count must be 1..20")
    try:
        date = datetime.date.fromisoformat(service_date) if service_date else datetime.date.today()
    except ValueError:
        raise HTTPException(status_code=400, detail="예배 날짜 형식이 올바르지 않습니다") from None

    # 콘티가 있으면 선택한 날짜(월/일)의 곡 + 송폼을 사용
    conti_songs = []
    if conti_raw.strip():
        weeks = conti.parse_conti(conti_raw, today=date)
        week = next((w for w in weeks if (w["date"].month, w["date"].day) == (date.month, date.day)), None)
        if not week or not week["songs"]:
            found = ", ".join(f"{w['date'].month}/{w['date'].day}" for w in weeks if w["songs"]) or "없음"
            raise HTTPException(
                status_code=400,
                detail=f"콘티에서 {date.month}/{date.day} 곡을 찾지 못했어요 (콘티에 있는 날짜: {found})",
            )
        conti_songs = week["songs"][:20]
        praise_count = len(conti_songs)

    sermon_phrases = [x.strip() for x in sermon_phrases_raw.splitlines() if x.strip()]

    plan = {
        "praise_count": int(praise_count),
        "date": date.isoformat(),
        "conti_songs": conti_songs,
        "prayer": prayer.strip(),
        "sermon_title": sermon_title.strip(),
        "sermon_phrases": sermon_phrases,
        "songs": {
            "praise": [],
            "offering": None,
            "closing": None,
        },
        "flags": {
            "include_offering": bool(int(include_offering)),
            "include_closing": bool(int(include_closing)),
        },
    }

    store = _store(request)
    plan_id = store.create(plan)
    return RedirectResponse(url=f"/step/2?plan_id={plan_id}", status_code=303)


@router.post("/api/plan/{plan_id}/songs/basic")
async def save_songs_basic(request: Request, plan_id: str):
    store = _store(request)
    plan = store.get(plan_id)
    if not plan:
        return RedirectResponse(url=f"/step/2?plan_id={plan_id}", status_code=303)

    praise_count = int(plan.get("praise_count", 3))
    form = await request.form()

    # 1) praise 구성
    praise = []
    for i in range(praise_count):
        title = str(form.get(f"praise_title_{i}", "")).strip()
        artist = str(form.get(f"praise_artist_{i}", "")).strip()
        song_form = str(form.get(f"praise_form_{i}", "")).strip()
        praise.append({"title": title, "artist": artist, "form": song_form, "lyrics": ""})

    # 2) offering/closing은 flags 안 믿고 "입력값 있으면" 무조건 저장
    offering = None
    ot = str(form.get("offering_title", "")).strip()
    oa = str(form.get("offering_artist", "")).strip()
    if ot:
        offering = {"title": ot, "artist": oa, "lyrics": ""}

    closing = None
    ct = str(form.get("closing_title", "")).strip()
    ca = str(form.get("closing_artist", "")).strip()
    if ct:
        closing = {"title": ct, "artist": ca, "lyrics": ""}

    plan["songs"]["praise"] = praise
    plan["songs"]["offering"] = offering
    plan["songs"]["closing"] = closing

    # 3) 여기서 즉시 크롤링(배치)
    batch = list(plan["songs"]["praise"])
    if offering:
        batch.append(offering)
    if closing:
        batch.append(closing)

    # lyrics/ 에 저장된 가사는 그대로 쓰고, 없는 곡만 크롤링 (메들리 'A+B'는 곡별로 따로 검색)
    to_crawl = []  # (곡, [크롤링할 조각])
    for s in batch:
        cached = conti.cached_lyrics(LYRICS_DIR, s["title"])
        if cached is not None:
            s["lyrics"] = cached
            continue
        parts = [t.strip() for t in s["title"].split("+") if t.strip()] or [s["title"]]
        artist = s["artist"] if len(parts) == 1 else ""
        to_crawl.append((s, [{"title": t, "artist": artist} for t in parts]))

    flat = [p for _, ps in to_crawl for p in ps]
    if flat:
        # 🌟🌟 Lock + 스레드풀: 버튼을 10번 연타해도 서버가 멈추지 않고 1개씩 순서대로 크롤링
        async with crawl_lock:
            results = await run_in_threadpool(fetch_lyrics_batch_melon, flat, True)
        got = {id(d): (lyrics or "") for d, lyrics in results}

        # 4) 결과 반영
        for s, ps in to_crawl:
            s["lyrics"] = "\n\n".join(got[id(p)] for p in ps).replace("\r\n", "\n")

    store.save(plan_id, plan)
    return RedirectResponse(url=f"/step/3?plan_id={plan_id}", status_code=303)


@router.post("/api/plan/{plan_id}/songs/lyrics")
async def save_lyrics(request: Request, plan_id: str):
    store = _store(request)
    plan = store.get(plan_id)
    if not plan:
        return RedirectResponse(url=f"/step/3?plan_id={plan_id}", status_code=303)

    form = await request.form()

    # praise
    for idx, s in enumerate(plan["songs"]["praise"]):
        s["lyrics"] = str(form.get(f"lyrics_praise_{idx}", "")).replace("\r\n", "\n")
        s["form"] = str(form.get(f"form_praise_{idx}", s.get("form", ""))).strip()

    # offering
    if plan["songs"].get("offering"):
        plan["songs"]["offering"]["lyrics"] = str(form.get("lyrics_offering", "")).replace("\r\n", "\n")

    # closing
    if plan["songs"].get("closing"):
        plan["songs"]["closing"]["lyrics"] = str(form.get("lyrics_closing", "")).replace("\r\n", "\n")

    store.save(plan_id, plan)
    return RedirectResponse(url=f"/step/4?plan_id={plan_id}", status_code=303)