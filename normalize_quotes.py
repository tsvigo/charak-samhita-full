#!/usr/bin/env python3
"""Нормализация уже переведённых RU-файлов: _термин_ → «термин».

Подчёркивания — наследие английской транслитерации санскрита,
при озвучке вслух звучат ужасно. Прогон идемпотентен.
"""
import re
import sys
from pathlib import Path

ROOT = Path("/home/v/projects/Чарак Самхита")
TARGETS = [ROOT / "gemini_full" / "out", ROOT / "gemini" / "out", ROOT / "ru"]

PAT = re.compile(r"(?<!_)_(?!_)([^_\n*]+?)(?<!_)_(?!_)")


def norm(s):
    return PAT.sub(r"«\1»", s)


def main():
    n_files, n_rep = 0, 0
    for d in TARGETS:
        if not d.exists():
            continue
        for f in sorted(d.rglob("*.ru.txt")):
            t = f.read_text(encoding="utf-8")
            nt, c = PAT.subn(r"«\1»", t)
            if c:
                f.write_text(nt, encoding="utf-8")
                n_files += 1
                n_rep += c
    print(f"Нормализованно файлов: {n_files}, замен: {n_rep}")


if __name__ == "__main__":
    if len(sys.argv) > 1:
        for a in sys.argv[1:]:
            p = Path(a)
            t = p.read_text(encoding="utf-8")
            p.write_text(PAT.sub(r"«\1»", t), encoding="utf-8")
            print(f"ok: {p}")
    else:
        main()
