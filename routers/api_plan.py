# routers/api_plan.py

from fastapi import APIRouter, Request, Form, HTTPException
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.concurrency import run_in_threadpool  # 🌟 추가: 서버 멈춤 방지용
import asyncio  # 🌟 추가: 연타 방지용 Lock

import datetime

from services import conti, lyrics_store
from services.melon import fetch_lyrics_batch_melon

MELON = "__melon__"   # 가사 선택: 멜론에서 새로 가져오기
PARTS = "__parts__"   # 가사 선택: 메들리를 곡별 저장 가사로 합치기

router = APIRouter()

crawl_lock = asyncio.Lock()

def _store(request: Request):
    return request.app.state.store


def plan_songs(plan: dict) -> list[tuple[str, dict]]:
    """가사가 필요한 곡 목록 [(키, 곡)] — 키는 폼 필드 이름에 사용 (praise_0, closing ...)"""
    out = [(f"praise_{i}", s) for i, s in enumerate(plan["songs"]["praise"])]
    for k in ("offering", "closing"):
        if plan["songs"].get(k):
            out.append((k, plan["songs"][k]))
    return out


def _parts(title: str) -> list[str]:
    return [t.strip() for t in title.split("+") if t.strip()]


def lyrics_options(song: dict) -> list[dict]:
    """가사 선택 화면에 보여줄 저장된 가사 후보 [{"id", "label", "text"}]"""
    opts = [{"id": f["name"], "label": f["name"][:-4], "text": f["text"]} for f in lyrics_store.find(song["title"])]
    parts = _parts(song["title"])
    if len(parts) > 1:
        found = [lyrics_store.find(p) for p in parts]
        if all(found):
            opts.append({
                "id": PARTS,
                "label": "곡별 저장 가사 합치기: " + " + ".join(f[0]["name"][:-4] for f in found),
                "text": "\n\n".join(f[0]["text"] for f in found),
            })
    return opts


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

    # 3) 저장된 가사가 하나라도 있으면 선택 화면으로, 없으면 바로 멜론 크롤링
    if any(lyrics_store.find(s["title"]) or len(_parts(s["title"])) > 1 for _, s in plan_songs(plan)):
        store.save(plan_id, plan)
        return RedirectResponse(url=f"/step/select?plan_id={plan_id}", status_code=303)

    await _apply_choices(plan, {key: MELON for key, _ in plan_songs(plan)})
    store.save(plan_id, plan)
    return RedirectResponse(url=f"/step/3?plan_id={plan_id}", status_code=303)


@router.post("/api/plan/{plan_id}/songs/select")
async def select_lyrics(request: Request, plan_id: str):
    store = _store(request)
    plan = store.get(plan_id)
    if not plan:
        return RedirectResponse(url=f"/step/select?plan_id={plan_id}", status_code=303)

    form = await request.form()
    await _apply_choices(plan, {key: str(form.get(f"choice_{key}", MELON)) for key, _ in plan_songs(plan)})
    store.save(plan_id, plan)
    return RedirectResponse(url=f"/step/3?plan_id={plan_id}", status_code=303)


async def _apply_choices(plan: dict, choices: dict[str, str]) -> None:
    """
    곡마다 선택한 가사를 채움. choices[키] = 저장 파일명 | PARTS | MELON
    save_name: 나중에 '가사 저장' 시 쓸 파일명 (저장된 가사를 골랐으면 그 파일을 덮어씀)
    """
    to_crawl = []  # (곡, [크롤링할 조각]) — 메들리 'A+B' 는 곡별로 따로 검색
    for key, s in plan_songs(plan):
        choice = choices.get(key, MELON)
        opts = {o["id"]: o for o in lyrics_options(s)}
        if choice in opts:  # 화면에서 온 값은 후보 목록에 있는 것만 인정
            s["lyrics"] = opts[choice]["text"]
            s["save_name"] = choice if choice != PARTS else lyrics_store.make_name(s["title"])
            continue
        parts = _parts(s["title"]) or [s["title"]]
        artist = s["artist"] if len(parts) == 1 else ""
        s["save_name"] = lyrics_store.make_name(s["title"], artist)
        to_crawl.append((s, [{"title": t, "artist": artist} for t in parts]))

    flat = [p for _, ps in to_crawl for p in ps]
    if not flat:
        return
    # 🌟🌟 Lock + 스레드풀: 버튼을 10번 연타해도 서버가 멈추지 않고 1개씩 순서대로 크롤링
    async with crawl_lock:
        results = await run_in_threadpool(fetch_lyrics_batch_melon, flat, True)
    got = {id(d): (lyrics or "") for d, lyrics in results}
    for s, ps in to_crawl:
        s["lyrics"] = "\n\n".join(got[id(p)] for p in ps).replace("\r\n", "\n")


@router.post("/api/plan/{plan_id}/lyrics/save")
async def save_lyrics_to_store(request: Request, plan_id: str):
    """PPT 생성 후: 체크한 곡의 가사를 저장소에 저장"""
    plan = _store(request).get(plan_id)
    if not plan:
        return JSONResponse({"error": "작업 정보가 만료됐어요. 처음부터 다시 진행해 주세요."}, status_code=404)
    form = await request.form()
    saved, failed = [], []
    for key, s in plan_songs(plan):
        if not form.get(f"save_{key}") or not s.get("lyrics", "").strip():
            continue
        name = s.get("save_name") or lyrics_store.make_name(s["title"], s.get("artist", ""))
        try:
            await run_in_threadpool(lyrics_store.save, name, s["lyrics"])
            saved.append(name)
        except Exception as e:
            failed.append(f"{name}: {e}")
    return JSONResponse({"saved": saved, "failed": failed, "persistent": lyrics_store.persistent()})


@router.post("/api/plan/{plan_id}/discard")
async def discard_plan(request: Request, plan_id: str):
    """PPT 생성 후: 가사를 저장하지 않고 이번 작업 정보 삭제"""
    _store(request).delete(plan_id)
    return JSONResponse({"ok": True})


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