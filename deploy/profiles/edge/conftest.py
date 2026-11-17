from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]


def _blocked_under(base: Path) -> list[str]:
    blocked_dir = ROOT / "blocked"
    if not blocked_dir.is_dir():
        return []
    prefix = base.relative_to(ROOT).as_posix() + "/"
    out = []
    for entry in sorted(blocked_dir.iterdir()):
        if entry.is_file():
            target = entry.read_text(encoding="utf-8").split(":", 1)[0].strip()
            if target.startswith(prefix):
                out.append(target[len(prefix):])
    return out


collect_ignore = _blocked_under(HERE)
collect_ignore_glob = collect_ignore
