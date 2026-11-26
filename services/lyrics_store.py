# services/lyrics_store.py — 가사 저장소 (찾기 / 읽기 / 저장)
#
# - lyrics/            : GitHub 에 같이 올라간 기본 가사 (읽기 전용)
# - out/lyrics_saved/  : 사이트에서 저장한 가사 (같은 파일명이면 이쪽이 우선)
# - 환경변수 LYRICS_REPO(예: hihwapyung/thepureum-lyrics, HF Dataset) + HF_TOKEN 이 있으면
#   저장할 때 Dataset 에도 올리고, 서버가 켜질 때 Dataset 에서 내려받음 → Space 재시작해도 유지
#   (shortcut: 둘 중 하나라도 없으면 서버 디스크에만 저장 → Space 재시작 시 사라짐)
import os
import re
import threading
from pathlib import Path

from services.conti import title_key

BASE_DIR = Path(__file__).resolve().parent.parent
BUNDLED_DIR = BASE_DIR / "lyrics"
SAVED_DIR = BASE_DIR / "out" / "lyrics_saved"
REPO = os.getenv("LYRICS_REPO", "").strip()

_lock = threading.Lock()
_synced = False


def persistent() -> bool:
    return bool(REPO and os.getenv("HF_TOKEN"))


def _sync_once():
    """Dataset 의 가사를 SAVED_DIR 로 한 번 내려받기 (실패해도 기본 가사로 계속 동작)"""
    global _synced
    with _lock:
        if _synced:
            return
        _synced = True
        if not persistent():
            return
        try:
            from huggingface_hub import snapshot_download
            snapshot_download(REPO, repo_type="dataset", local_dir=SAVED_DIR, allow_patterns=["*.txt"])
        except Exception as e:  # 네트워크/권한 문제 → 로그만 남기고 기본 가사 사용
            print(f"[lyrics_store] Dataset 동기화 실패: {e}")


def _files() -> dict[str, Path]:
    _sync_once()
    files = {p.name: p for p in BUNDLED_DIR.glob("*.txt")}
    files.update({p.name: p for p in SAVED_DIR.glob("*.txt")})
    return files


def _read(fp: Path) -> str:
    return fp.read_text(encoding="utf-8").replace("\r\n", "\n").strip()


def find(title: str) -> list[dict]:
    """제목이 같은 저장 가사 목록 (띄어쓰기·대소문자·'_아티스트' 무시) → [{"name", "text"}]"""
    if not title.strip():
        return []
    key = title_key(title)
    return [{"name": n, "text": _read(p)} for n, p in sorted(_files().items()) if title_key(Path(n).stem) == key]


def read(name: str) -> str | None:
    fp = _files().get(name)
    return _read(fp) if fp else None


def make_name(title: str, artist: str = "") -> str:
    """곡 제목(+아티스트) → 안전한 파일명. 경로 문자 등은 공백으로 바꿈"""
    stem = f"{title}_{artist}" if artist.strip() else title
    stem = re.sub(r'[\\/:*?"<>|\x00-\x1f]', " ", stem).strip().strip(".")[:100].strip()
    return f"{stem or '제목없음'}.txt"


def save(name: str, text: str) -> None:
    """가사 저장. Dataset 업로드 실패는 예외로 올려서 화면에 알림"""
    if name != make_name(name[:-4]) or not name.endswith(".txt"):
        raise ValueError(f"잘못된 파일명: {name!r}")
    text = text.replace("\r\n", "\n").strip() + "\n"
    SAVED_DIR.mkdir(parents=True, exist_ok=True)
    (SAVED_DIR / name).write_text(text, encoding="utf-8")
    if persistent():
        from huggingface_hub import HfApi
        HfApi().upload_file(
            path_or_fileobj=text.encode("utf-8"),
            path_in_repo=name,
            repo_id=REPO,
            repo_type="dataset",
            commit_message=f"가사 저장: {name}",
        )
