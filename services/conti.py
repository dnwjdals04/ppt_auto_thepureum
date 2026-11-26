# services/conti.py — 콘티 텍스트 / 송폼 / 파트 표시된 가사 해석 (더푸름_자동화/conti.py 와 동일)
import datetime
import re

# 날짜 줄: '11/1', '5/24', '📌 7.5 콘티' (앞의 이모지 허용, '3. 10000 reasons' 같은 곡 번호는 제외)
DATE_RE = re.compile(r"^\W*(\d{1,2})[/.](\d{1,2})(?!\d)")
SONG_RE = re.compile(r"^\s*\d+\s*[.)]\s*(.+?)\s*$")             # '1. 곡명'
HEADER_RE = re.compile(r"^\s*[^\w\s(\[=*\-'\"]+\s*(\S.*?)\s*$")  # '❤️ 곡명(Bb)' 처럼 이모지로 시작
DASH_FORM_RE = re.compile(r"^[\sA-Za-z0-9()'’‘`\-]+$")           # 'Intro(8)-A1-(4)-B'
PART_RE = re.compile(r"^\s*(세션|싱어)\s*:\s*")                     # '세션: ...' / '싱어: ...'
# 송폼 단어: Intro/Inter/Outro 등 + 파트 이름(A, A1, B', C2 ...)
TOKEN_RE = re.compile(r"(?i)(intro|into|inter|interlude|outro|ending|[a-z]\d*'?)")
KEY_RE = re.compile(r"\s*\(\s*[A-G][#b♭♯]?m?\s*(?:[/→\-~,].*)?\)\s*$")  # 제목 끝 키 표시 '(Bb)' '(G / OG: A)'
TAG_RE = re.compile(r"^\s*\[(.+?)\]\s*$")           # 가사 파일의 [A1] 같은 파트 표시


def _norm_quote(s: str) -> str:
    return re.sub(r"[’‘`]", "'", s.strip())


def resolve_date(month: int, day: int, today: datetime.date) -> datetime.date:
    """연도 없는 날짜 → 오늘 기준 가까운 연도 (12월에 1월 콘티를 받아도 다음 해로)"""
    d = datetime.date(today.year, month, day)
    if (today - d).days > 180:
        d = d.replace(year=today.year + 1)
    return d


def _clean_title(t: str) -> str:
    return KEY_RE.sub("", t).strip()


def form_tokens(line: str) -> list[str] | None:
    """
    송폼 줄이면 토큰 목록, 아니면 None
    - 'Intro(8)-A1-(4)-B'                 → ['Intro(8)', 'A1', '(4)', 'B']
    - 'Intro [A1 B](승현)' / 'Inter(키업) A4 B' → ['Intro', 'A1', 'B'] / ['Inter', 'A4', 'B']  (괄호 메모·[ ]·* 무시)
    """
    line = PART_RE.sub("", line).strip()
    if "-" in line and DASH_FORM_RE.match(line):
        toks = [t.strip() for t in line.split("-") if t.strip()]
        return toks or None
    line = re.sub(r"\([^)]*\)", " ", line)
    toks = line.replace("[", " ").replace("]", " ").replace("*", " ").split()
    if toks and all(TOKEN_RE.fullmatch(_norm_quote(t)) for t in toks):
        return toks
    return None


def parse_conti(text: str, today: datetime.date | None = None) -> list[dict]:
    """
    콘티 전체 텍스트 → [{"date": date, "songs": [{"title": str, "form": str}]}]
    - 곡: '1. 곡명' / '❤️ 곡명(키)' / 번호 없이 송폼 줄 바로 위의 줄
    - 송폼: 'Intro-A-B' 한 줄 또는 여러 줄 ('Intro A' / 'Inter B B' ...) → 'Intro-A-Inter-B-B' 로 합침
    - '세션:' / '싱어:' 가 둘 다 있으면 싱어 송폼 사용 (가사는 싱어 기준)
    - 날짜 줄이 없으면 today 날짜의 콘티로 봄
    - 곡 번호는 믿지 않음 (콘티에 1,2,1 처럼 잘못 적히는 경우가 있음), 그 외 줄은 무시
    """
    today = today or datetime.date.today()
    weeks: list[dict] = []
    cur = None   # 송폼 줄을 받을 곡
    prev = None  # 바로 윗줄 (번호 없는 곡 제목 후보)

    def new_song(title: str) -> dict:
        if not weeks:
            weeks.append({"date": today, "songs": []})
        song = {"title": _clean_title(title), "form": "", "_forms": {}, "_part": ""}
        weeks[-1]["songs"].append(song)
        return song

    for line in text.splitlines():
        if not line.strip():
            prev = None
            continue
        m = DATE_RE.match(line)
        if m:
            weeks.append({"date": resolve_date(int(m.group(1)), int(m.group(2)), today), "songs": []})
            cur = prev = None
            continue
        toks = form_tokens(line)
        if toks:
            if prev is not None:
                cur = new_song(prev)
            if cur is not None:
                p = PART_RE.match(line)
                if p:
                    cur["_part"] = p.group(1)
                cur["_forms"].setdefault(cur["_part"], []).extend(toks)
            prev = None
            continue
        m = SONG_RE.match(line) or HEADER_RE.match(line)
        if m and not line.lstrip().startswith("="):
            cur, prev = new_song(m.group(1)), None
            continue
        cur, prev = None, line.strip()

    for w in weeks:
        for s in w["songs"]:
            forms = s.pop("_forms")
            s.pop("_part")
            s["form"] = "-".join(forms.get("싱어") or forms.get("") or forms.get("세션") or [])
    return [w for w in weeks if w["songs"]] or weeks


def parse_form(form: str) -> list[tuple[str, str]]:
    """
    'Intro(8)-A1-(4)-B-Inter-C-Outro'
      → [("intro",""), ("section","A1"), ("blank",""), ("section","B"), ("blank",""), ("section","C"), ("blank","")]
    Intro = 제목 슬라이드 그대로 / (n)·Inter·Outro = 빈 슬라이드
    """
    out = []
    for tok in form.split("-"):
        tok = _norm_quote(tok)
        if not tok:
            continue
        if re.fullmatch(r"(?i)(intro|into)\s*(\(\d+\))?", tok):  # 'Into' 오타도 허용
            out.append(("intro", ""))
        elif re.fullmatch(r"(?i)(\(\d+\)|(inter|interlude|outro|ending)\s*(\(\d+\))?)", tok):
            out.append(("blank", ""))
        else:
            out.append(("section", tok))
    return out


def parse_sections(lyrics: str) -> dict[str, list[str]]:
    """
    [A1] / [B] 표시가 있는 가사 → {"A1": [줄...], "B": [줄...]}  (빈 줄 유지, 앞뒤 빈 줄 제거)
    표시가 하나도 없으면 {} 반환
    """
    sections: dict[str, list[str]] = {}
    cur = None
    for raw in lyrics.replace("\r\n", "\n").split("\n"):
        m = TAG_RE.match(raw)
        if m:
            cur = _norm_quote(m.group(1))
            sections.setdefault(cur, [])
            continue
        if cur is not None:
            sections[cur].append(raw.strip())
    for k, lines in sections.items():
        while lines and not lines[0]:
            lines.pop(0)
        while lines and not lines[-1]:
            lines.pop()
    return sections


def find_section(sections: dict, label: str) -> str | None:
    """정확히 → 대소문자 무시 → ' 와 숫자 무시 (b → B1, B' → B, A1 → A) 순으로 찾기"""
    label = _norm_quote(label)
    if label in sections:
        return label
    for k in sections:
        if k.upper() == label.upper():
            return k
    loose = lambda s: re.sub(r"[\d']", "", s).upper()
    for k in sections:
        if loose(k) == loose(label):
            return k
    return None


def chunk_lines(lines: list[str]) -> list[str]:
    """문단(빈 줄 구분)마다 2줄씩 묶어 슬라이드 텍스트로"""
    slides, buf = [], []
    for line in lines + [""]:
        if line:
            buf.append(line)
            if len(buf) == 2:
                slides.append("\n".join(buf))
                buf = []
        elif buf:
            slides.append(buf[0])
            buf = []
    return slides


def plain_slides(lyrics: str) -> list[str]:
    """파트 표시 없는 가사: 원래 순서대로 2줄씩, 문단 사이에 빈 슬라이드"""
    paras = [p.strip() for p in re.split(r"\n\s*\n", lyrics.replace("\r\n", "\n").strip()) if p.strip()]
    slides = []
    for i, para in enumerate(paras):
        if i:
            slides.append("")
        slides += chunk_lines([l.strip() for l in para.split("\n")])
    return slides


def form_slides(lyrics: str, form: str) -> tuple[list[str], list[str]]:
    """
    송폼 순서대로 가사 슬라이드 텍스트 목록 생성 ("" = 빈 슬라이드)
    return (slides, warnings)
    """
    sections = parse_sections(lyrics)
    if not form or not sections:
        warn = [] if not form else ["가사에 [A1] 같은 파트 표시가 없어 송폼 미적용(가사 순서대로)"]
        return plain_slides(lyrics), warn

    slides, warnings = [], []
    for kind, label in parse_form(form):
        if kind == "blank":
            slides.append("")
        elif kind == "section":
            key = find_section(sections, label)
            if key is None:
                warnings.append(f"송폼의 '{label}' 파트를 가사에서 못 찾아 건너뜀 (있는 파트: {', '.join(sections)})")
                continue
            if key != _norm_quote(label):
                warnings.append(f"'{label}' → [{key}] 로 대신 사용")
            slides += chunk_lines(sections[key])
    return slides, warnings


def title_key(name: str) -> str:
    """'나 주님의 기쁨 되기_아티스트' → '나주님의기쁨되기' (파일명·제목 비교용)"""
    return re.sub(r"\s+", "", name.split("_")[0]).lower()


# =========================
# 셀프 테스트: python -m services.conti
# =========================
if __name__ == "__main__":
    sample = """11월 찬양

11/1

1. 성도여 다함께

Intro(8)-A1-A1-B1-(4)-A2-A2-B2-(2)-A3-B3-(8)-A1-A2-A3-B3-B1-b-(8)

3. 우리 주 하나님

Intro(12)-A1-B-(2)-A2-B-B-C-C-B’-B’

싱어 은민 은빈 혜원 세윤
어쿠 -

11/8

1. 천년이 두 번 지나도
Intro(4)-A-B-C-(10)-B-C-(8)
1. 우리 살아가는 모든 날들이+밤이나 낮이나

Intro(4)-A-A-B-(2)-A-A-B-B-C-C-C
"""
    weeks = parse_conti(sample, datetime.date(2026, 10, 20))
    assert [w["date"] for w in weeks] == [datetime.date(2026, 11, 1), datetime.date(2026, 11, 8)]
    assert [s["title"] for s in weeks[0]["songs"]] == ["성도여 다함께", "우리 주 하나님"]
    assert weeks[0]["songs"][1]["form"].endswith("B’-B’")
    assert weeks[1]["songs"][1]["title"] == "우리 살아가는 모든 날들이+밤이나 낮이나"
    assert weeks[1]["songs"][1]["form"].startswith("Intro(4)")
    assert resolve_date(1, 4, datetime.date(2026, 12, 20)) == datetime.date(2027, 1, 4)

    # 번호 없는 콘티 + 'Into' 오타
    plain = "11/29\n주의 이름 높이며\nInto(8)-A1-(4)-A-B-(4)-A-B-B-(4)-B'-B\n\n나의 왕 나의 주\nIntro(8)-A-B-C\n싱어 하경 은빈\n메인 지희\n"
    w = parse_conti(plain, datetime.date(2026, 11, 26))
    assert [(s["title"], s["form"][:8]) for s in w[0]["songs"]] == [("주의 이름 높이며", "Into(8)-"), ("나의 왕 나의 주", "Intro(8)")], w
    assert parse_form("Into(8)-A")[0] == ("intro", "")

    # ❤️ 형식: 여러 줄 송폼, 괄호 메모, 키 표시, '📌 7.5' 날짜
    heart = """📌 7.5 콘티 - 악보포함

= 확인 후 체크 표시✅ 부탁드립니다 =

❤️ Jehovah(Bb)
    Intro [A1 B](승현)
    Inter A2 B
    Inter [C C](승현)
    D D D B B
    Outro

❤️ 지금은 엘리야 때처럼(Bb)
    C(승현) C(다같이)
    Inter A1 B1 C
"""
    w = parse_conti(heart, datetime.date(2026, 7, 1))
    assert w[0]["date"] == datetime.date(2026, 7, 5), w
    assert [s["title"] for s in w[0]["songs"]] == ["Jehovah", "지금은 엘리야 때처럼"], w
    assert w[0]["songs"][0]["form"] == "Intro-A1-B-Inter-A2-B-Inter-C-C-D-D-D-B-B-Outro", w
    assert w[0]["songs"][1]["form"] == "C-C-Inter-A1-B1-C", w

    # 세션/싱어 → 싱어 송폼, 날짜 줄 없음 → today 날짜
    parts = """❤️ 크신 내 주님(G / OG: A)
세션: Intro A1 A2 B
    Inter C C
    *Outro
싱어: Intro A1(승현) A2(다같이) B(다같이 /화: 여자싱어)
    *Inter B B C C

❤️ 주의 나라(G→A)
세션: (멘트) A
싱어: (멘트) A(승현)
    Inter A(다같이) B A
"""
    w = parse_conti(parts, datetime.date(2026, 7, 5))
    assert w[0]["date"] == datetime.date(2026, 7, 5)
    assert [(s["title"], s["form"]) for s in w[0]["songs"]] == [
        ("크신 내 주님", "Intro-A1-A2-B-Inter-B-B-C-C"), ("주의 나라", "A-Inter-A-B-A")], w
    assert parse_form("A-Inter-B-Outro") == [("section", "A"), ("blank", ""), ("section", "B"), ("blank", "")]
    assert form_tokens("Thank You LORD") is None and form_tokens("싱어 하경 은빈") is None
    assert _clean_title("Way Maker(Acoustic)") == "Way Maker(Acoustic)"

    assert parse_form("Intro(8)-A1-(4)-B’") == [("intro", ""), ("section", "A1"), ("blank", ""), ("section", "B'")]

    lyr = "[A1]\n가\n나\n다\n\n[B1]\n라\n마\n\n[B']\n바\n"
    secs = parse_sections(lyr)
    assert secs == {"A1": ["가", "나", "다"], "B1": ["라", "마"], "B'": ["바"]}
    assert find_section(secs, "b") == "B1"
    assert find_section(secs, "B’") == "B'"
    assert find_section(secs, "C") is None

    slides, warns = form_slides(lyr, "Intro(4)-A1-(2)-b-B’-C")
    assert slides == ["가\n나", "다", "", "라\n마", "바"], slides
    assert len(warns) == 2  # b→B1 대체, C 없음

    slides, warns = form_slides("가\n나\n다\n\n라", "Intro-A-B")
    assert slides == ["가\n나", "다", "", "라"] and warns
    print("conti.py self-test OK")
