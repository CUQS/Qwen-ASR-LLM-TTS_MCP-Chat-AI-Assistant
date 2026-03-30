from __future__ import annotations

from datetime import datetime
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
TODO_NAME = "todo.md"
VALID_UPDATE_MODES = {"replace", "append", "prepend"}


def _ensure_data_dir() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)


def _parse_timestamp(timestamp: str | None) -> datetime:
    if not timestamp:
        return datetime.now().astimezone()

    ts = timestamp.strip()
    for fmt in ("%Y%m%d_%H%M%S", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.strptime(ts, fmt).astimezone()
        except ValueError:
            continue

    try:
        return datetime.fromisoformat(ts).astimezone()
    except ValueError as exc:
        raise ValueError(
            "Invalid timestamp format. Use ISO format, "
            "'YYYY-MM-DD HH:MM:SS' or 'YYYYMMDD_HHMMSS'."
        ) from exc


def _resolve_memo_path(relative_path: str) -> Path:
    if not relative_path or not relative_path.strip():
        raise ValueError("Memo path must not be empty.")

    _ensure_data_dir()
    target = (DATA_DIR / relative_path).resolve()
    data_root = DATA_DIR.resolve()
    if not target.is_relative_to(data_root):
        raise ValueError("Invalid memo path; path traversal is not allowed.")
    return target


def _relative_posix(path: Path) -> str:
    return path.resolve().relative_to(DATA_DIR.resolve()).as_posix()


def _compose_markdown(title: str, content: str, created: datetime) -> str:
    created_iso = created.isoformat(timespec="seconds")
    header_lines = [
        f"# {title}",
        "",
        f"- created_at: {created_iso}",
        f"- updated_at: {created_iso}",
        "",
    ]
    body = content.rstrip()
    if body:
        header_lines.append(body)
    return "\n".join(header_lines).rstrip() + "\n"


def create_memo(content: str, title: str = "", timestamp: str | None = None) -> dict:
    """创建一条新的 Markdown 备忘录并返回文件信息。"""
    dt = _parse_timestamp(timestamp)
    _ensure_data_dir()

    month_dir = DATA_DIR / f"{dt.year:04d}" / f"{dt.month:02d}"
    month_dir.mkdir(parents=True, exist_ok=True)

    base_name = dt.strftime("%Y%m%d_%H%M%S")
    memo_path = month_dir / f"{base_name}.md"
    seq = 1
    while memo_path.exists():
        memo_path = month_dir / f"{base_name}_{seq:02d}.md"
        seq += 1

    memo_title = title.strip() if title and title.strip() else f"Memo {dt.strftime('%Y-%m-%d %H:%M:%S')}"
    memo_path.write_text(_compose_markdown(memo_title, content, dt), encoding="utf-8")

    return {
        "ok": True,
        "path": _relative_posix(memo_path),
        "absolute_path": str(memo_path),
        "created_at": dt.isoformat(timespec="seconds"),
    }


def list_memos(
    year: int | None = None,
    month: int | None = None,
    limit: int = 100,
    include_todo: bool = False,
) -> dict:
    """列出备忘录文件，支持按年/月过滤，并可选择是否包含 todo.md。"""
    _ensure_data_dir()
    if month is not None and year is None:
        raise ValueError("When month is provided, year is required.")
    if month is not None and not (1 <= month <= 12):
        raise ValueError("Month must be between 1 and 12.")
    if limit <= 0:
        raise ValueError("Limit must be greater than 0.")

    root = DATA_DIR
    if year is not None:
        root = root / f"{year:04d}"
    if month is not None:
        root = root / f"{month:02d}"

    if not root.exists():
        return {"ok": True, "count": 0, "items": []}

    files = sorted(root.rglob("*.md"), key=lambda p: p.stat().st_mtime, reverse=True)
    items = []
    for file_path in files:
        if not include_todo and file_path.name.lower() == TODO_NAME:
            continue
        stat = file_path.stat()
        items.append(
            {
                "path": _relative_posix(file_path),
                "size": stat.st_size,
                "updated_at": datetime.fromtimestamp(stat.st_mtime).astimezone().isoformat(timespec="seconds"),
            }
        )
        if len(items) >= limit:
            break

    return {"ok": True, "count": len(items), "items": items}


def read_memo(path: str) -> dict:
    """按相对路径读取备忘录内容。"""
    memo_path = _resolve_memo_path(path)
    if not memo_path.exists() or not memo_path.is_file():
        raise FileNotFoundError(f"Memo not found: {path}")

    content = memo_path.read_text(encoding="utf-8")
    stat = memo_path.stat()
    return {
        "ok": True,
        "path": _relative_posix(memo_path),
        "updated_at": datetime.fromtimestamp(stat.st_mtime).astimezone().isoformat(timespec="seconds"),
        "content": content,
    }


def update_memo(path: str, content: str, mode: str = "replace") -> dict:
    """更新指定备忘录内容，支持 replace/append/prepend 三种模式。"""
    update_mode = mode.strip().lower()
    if update_mode not in VALID_UPDATE_MODES:
        raise ValueError(f"Invalid mode: {mode}. Supported modes: {sorted(VALID_UPDATE_MODES)}")

    memo_path = _resolve_memo_path(path)
    if not memo_path.exists() or not memo_path.is_file():
        raise FileNotFoundError(f"Memo not found: {path}")

    current = memo_path.read_text(encoding="utf-8")
    payload = content or ""
    if update_mode == "replace":
        merged = payload
    elif update_mode == "append":
        separator = "\n" if current and not current.endswith("\n") else ""
        merged = f"{current}{separator}{payload}"
    else:
        separator = "\n" if payload and not payload.endswith("\n") else ""
        merged = f"{payload}{separator}{current}"

    memo_path.write_text(merged, encoding="utf-8")
    stat = memo_path.stat()
    return {
        "ok": True,
        "path": _relative_posix(memo_path),
        "absolute_path": str(memo_path),
        "mode": update_mode,
        "size": stat.st_size,
        "updated_at": datetime.fromtimestamp(stat.st_mtime).astimezone().isoformat(timespec="seconds"),
    }


def delete_memo(path: str) -> dict:
    """删除指定备忘录文件。"""
    memo_path = _resolve_memo_path(path)
    if not memo_path.exists() or not memo_path.is_file():
        raise FileNotFoundError(f"Memo not found: {path}")

    memo_path.unlink()
    return {"ok": True, "deleted": True, "path": path}


def update_todo(content: str, mode: str = "append") -> dict:
    """更新 todo.md，支持 replace/append/prepend 三种模式。"""
    _ensure_data_dir()
    todo_path = DATA_DIR / TODO_NAME

    update_mode = mode.strip().lower()
    if update_mode not in VALID_UPDATE_MODES:
        raise ValueError(f"Invalid mode: {mode}. Supported modes: {sorted(VALID_UPDATE_MODES)}")

    current = todo_path.read_text(encoding="utf-8") if todo_path.exists() else ""
    payload = content or ""
    if update_mode == "replace":
        merged = payload
    elif update_mode == "append":
        separator = "\n" if current and not current.endswith("\n") else ""
        merged = f"{current}{separator}{payload}"
    else:
        separator = "\n" if payload and not payload.endswith("\n") else ""
        merged = f"{payload}{separator}{current}"

    todo_path.write_text(merged, encoding="utf-8")
    stat = todo_path.stat()
    return {
        "ok": True,
        "path": _relative_posix(todo_path),
        "absolute_path": str(todo_path),
        "mode": update_mode,
        "size": stat.st_size,
        "updated_at": datetime.fromtimestamp(stat.st_mtime).astimezone().isoformat(timespec="seconds"),
    }
