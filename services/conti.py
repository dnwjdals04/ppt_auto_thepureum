# services/conti.py — 콘티 텍스트 / 송폼 / 파트 표시된 가사 해석 (더푸름_자동화/conti.py 와 동일)
import datetime
import re

DATE_RE = re.compile(r"^\s*(\d{1,2})\s*/\s*(\d{1,2})\b")
SONG_RE = re.compile(r"^\s*\d+\s*[.)]\s*(.+?)\s*$")
FORM_RE = re.compile(r"^[\sA-Za-z0-9()'’‘`\-]+$")  # 송폼 줄: 영문/숫자/괄호/하이픈만
TAG_RE = re.compile(r"^\s*\[(.+?)\]\s*$")           # 가사 파일의 [A1] 같은 파트 표시


def _norm_quote(s: str) -> str:
    return re.sub(r"[’‘`]", "'", s.strip())


def resolve_date(month: int, day: int, today: datetime.date) -> datetime.date:
    """연도 없는 날짜 → 오늘 기준 가까운 연도 (12월에 1월 콘티를 받아도 다음 해로)"""
    d = datetime.date(today.year, month, day)
    if (today - d).days > 180:
        d = d.replace(year=today.year + 1)
    return d


def parse_conti(text: str, today: datetime.date | None = None) -> list[dict]:
    """
    콘티 전체 텍스트 → [{"date": date, "songs": [{"title": str, "form": str}]}]
    - 곡: '1. 곡명' 줄, 또는 번호 없이 송폼 줄 바로 위의 줄
    - 곡 번호는 믿지 않음 (콘티에 1,2,1 처럼 잘못 적히는 경우가 있음)
    - 싱어/세션 등 그 외 줄은 무시
    """
    today = today or datetime.date.today()
    weeks: list[dict] = []
    prev = None  # 직전 줄 (번호 없는 곡 제목 후보)
    for line in text.splitlines():
        if not line.strip():
            continue
        m = DATE_RE.match(line)
        if m:
            weeks.append({"date": resolve_date(int(m.group(1)), int(m.group(2)), today), "songs": []})
            prev = None
            continue
        if not weeks:
            continue  # "11월 찬양" 같은 머리말
        songs = weeks[-1]["songs"]
        m = SONG_RE.match(line)
        if m:
            songs.append({"title": m.group(1), "form": ""})
            prev = None
            continue
        if "-" in line and FORM_RE.match(line):
            if prev is not None:
                songs.append({"title": prev, "form": line.strip()})
            elif songs and not songs[-1]["form"]:
                songs[-1]["form"] = line.strip()
            prev = None
            continue
        prev = line.strip()
    return weeks


def parse_form(form: str) -> list[tuple[str, str]]:
    """
    'Intro(8)-A1-(4)-B' → [("intro",""), ("section","A1"), ("blank",""), ("section","B")]
    """
    out = []
    for tok in form.split("-"):
        tok = _norm_quote(tok)
        if not tok:
            continue
        if re.fullmatch(r"(?i)(intro|into)\s*(\(\d+\))?", tok):  # 'Into' 오타도 허용
            out.append(("intro", ""))
        elif re.fullmatch(r"\(\d+\)", tok):
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


def _title_key(name: str) -> str:
    return re.sub(r"\s+", "", name.split("_")[0]).lower()


def cached_lyrics(lyrics_dir, title: str) -> str | None:
    """
    lyrics/ 에서 '제목.txt' 또는 '제목_아티스트.txt' 찾기 (띄어쓰기·대소문자 무시)
    메들리 'A+B' 는 통째 파일이 없으면 곡별 파일을 빈 줄로 이어붙임. 하나라도 없으면 None
    """
    if not title.strip():
        return None
    for fp in sorted(lyrics_dir.glob("*.txt")):
        if _title_key(fp.stem) == _title_key(title):
            return fp.read_text(encoding="utf-8").replace("\r\n", "\n").strip()
    parts = [t.strip() for t in title.split("+") if t.strip()]
    if len(parts) > 1:
        texts = [cached_lyrics(lyrics_dir, p) for p in parts]
        if all(t is not None for t in texts):
            return "\n\n".join(texts)
    return None


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
