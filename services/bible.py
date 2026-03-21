import re
from pathlib import Path

BOOK_MAP = {
    "창세기": "창", "출애굽기": "출", "레위기": "레", "민수기": "민", "신명기": "신", "여호수아": "수",
    "사사기": "삿", "룻기": "룻", "사무엘상": "삼상", "사무엘하": "삼하", "열왕기상": "왕상", "열왕기하": "왕하",
    "역대상": "대상", "역대하": "대하", "에스라": "스", "느헤미야": "느", "에스더": "에", "욥기": "욥",
    "시편": "시", "잠언": "잠", "전도서": "전", "아가": "아", "이사야": "사", "예레미야": "렘",
    "예레미야애가": "애", "에스겔": "겔", "다니엘": "단", "호세아": "호", "요엘": "욜", "아모스": "암",
    "오바댜": "옵", "요나": "욘", "미가": "미", "나훔": "나", "하박국": "합", "스바냐": "습",
    "학개": "학", "스가랴": "슥", "말라기": "말", "마태복음": "마", "마가복음": "막", "누가복음": "눅",
    "요한복음": "요", "사도행전": "행", "로마서": "롬", "고린도전서": "고전", "고린도후서": "고후",
    "갈라디아서": "갈", "에베소서": "엡", "빌립보서": "빌", "골로새서": "골", "데살로니가전서": "살전",
    "데살로니가후서": "살후", "디모데전서": "딤전", "디모데후서": "딤후", "디도서": "딛", "빌레몬서": "몬",
    "히브리서": "히", "야고보서": "약", "베드로전서": "벧전", "베드로후서": "벧후", "요한일서": "요일",
    "요한이서": "요이", "요한삼서": "요삼", "유다서": "유", "요한계시록": "계"
}


def parse_range(phrase: str):
    m = re.search(r"^\s*(.+?)\s*(\d+)\s*장\s*(\d+)(?:\s*-\s*(\d+))?\s*절\s*$", phrase)
    if not m:
        return (None, None, None, None)
    book = m.group(1).strip()
    chapter = int(m.group(2))
    start = int(m.group(3))
    end = int(m.group(4)) if m.group(4) else start
    return (book, chapter, start, end)


def scroll_bible(bible_dir: Path, book: str, chapter: int, start_v: int, end_v: int):
    if not book:
        return ["(입력 양식 오류)"]
        
    abbr = BOOK_MAP.get(book, book)
    fp = Path(bible_dir) / f"{book}.txt"
    
    if not fp.exists():
        return ["(성경 파일 없음)"] * (end_v - start_v + 1)
        
    pat = re.compile(rf"^\s*{re.escape(abbr)}\s*(\d+)\s*:\s*(\d+)\s*(.*)$")
    verses_dict = {}
    
    # ✅ 핵심 수정: 인코딩 자동 감지 (UTF-8 먼저 시도, 에러 나면 CP949로 폴백)
    try:
        with open(fp, "r", encoding="utf-8") as f:
            lines = f.readlines()
    except UnicodeDecodeError:
        with open(fp, "r", encoding="cp949") as f:
            lines = f.readlines()
            
    # 읽어온 줄들을 처리
    for line in lines:
        line = line.strip()
        if not line:
            continue
            
        m = pat.match(line)
        if not m:
            continue
            
        ch = int(m.group(1))
        vs = int(m.group(2))
        body = m.group(3).strip()
        body = re.sub(r"<[^>]*>", "", body).strip()
        
        # 정확한 장/절에 해당하는 본문만 딕셔너리에 저장
        if ch == chapter and (start_v <= vs <= end_v):
            verses_dict[vs] = body

    # start_v부터 end_v까지 정확한 번호를 찾아 리스트 완성
    result = []
    for vno in range(start_v, end_v + 1):
        result.append(verses_dict.get(vno, "(성경 텍스트 누락 또는 포맷 오류)"))
        
    return result
