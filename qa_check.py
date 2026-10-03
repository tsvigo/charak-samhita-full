#!/usr/bin/env python3
"""QA-проверка перевода Чарак Самхиты (идемпотентна, только читает).

Проверяет 4 вещи:
  1. Пропуски чанков — нет RU-файла или он пустой.
  2. Незакрытые кавычки «» и остатки подчёркиваний _..._.
  3. Битый markdown — пустые заголовки ##, строки из одних маркеров.
  4. Короткие огрызки — RU много короче EN (модель оборвала ответ).

Запуск: python3 qa_check.py [--work gemini_full]
Отчёт: печать + qa_report.txt
"""
import argparse
import json
import re
from pathlib import Path

ROOT = Path("/home/v/projects/Чарак Самхита")

QUOTE_OPEN = "«"
QUOTE_CLOSE = "»"
LEFTOVER = re.compile(r"(?<!_)_(?!_)([^_\n*]+?)(?<!_)_(?!_)")


def check_chunk(en_text, ru_text):
    problems = []
    en_w = len(en_text.split())
    ru_w = len(ru_text.split())
    if ru_w == 0:
        problems.append("пустой перевод")
        return problems, en_w, ru_w
    if QUOTE_OPEN in ru_text or QUOTE_CLOSE in ru_text:
        if ru_text.count(QUOTE_OPEN) != ru_text.count(QUOTE_CLOSE):
            problems.append(
                f"незакрытые кавычки: «={ru_text.count(QUOTE_OPEN)} »={ru_text.count(QUOTE_CLOSE)}")
    m = LEFTOVER.search(ru_text)
    if m:
        problems.append(f"остаток подчёркиваний: …{m.group(0)[:40]}…")
    for i, line in enumerate(ru_text.splitlines(), 1):
        s = line.strip()
        if s in ("##", "#", "*", "-", "«", "»"):
            problems.append(f"битый markdown, строка {i}: {s!r}")
            break
    if en_w > 1500 and ru_w < 300:
        problems.append(f"огрызок: RU {ru_w} слов при EN {en_w}")
    elif en_w > 0 and ru_w / en_w < 0.25:
        problems.append(f"подозрительно коротко: RU {ru_w} / EN {en_w}")
    return problems, en_w, ru_w


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--work", default="gemini_full")
    args = ap.parse_args()
    work = ROOT / args.work
    manifest_p = work / "manifest.json"
    if not manifest_p.exists():
        print(f"Нет {manifest_p} — сначала split")
        return
    manifest = json.loads(manifest_p.read_text(encoding="utf-8"))
    part_dir = work / "parts"
    out_dir = work / "out"

    if "files" in manifest:  # полный корпус
        items = [(f["stem"], f["parts"]) for f in manifest["files"]]
    else:  # пилот
        items = [(manifest["stem"], manifest["parts"])]

    total = bad = 0
    lines = []
    for stem, n in items:
        for kk in range(1, n + 1):
            total += 1
            name = f"{stem}.p{kk:02d}"
            en_f = part_dir / f"{name}.en.txt"
            ru_f = out_dir / f"{name}.ru.txt"
            if not en_f.exists():
                lines.append(f"[MISS-EN] {name}: нет английского чанка")
                bad += 1
                continue
            if not ru_f.exists():
                lines.append(f"[TODO] {name}: перевода ещё нет")
                continue
            en_t = en_f.read_text(encoding="utf-8")
            ru_t = ru_f.read_text(encoding="utf-8")
            probs, en_w, ru_w = check_chunk(en_t, ru_t)
            if probs:
                bad += 1
                lines.append(f"[BAD] {name} (EN {en_w} / RU {ru_w}): " + "; ".join(probs))
    print(f"Проверено чанков: {total}, проблемных/отсутствующих: {bad}")
    for l in lines:
        print(l)
    rep = ROOT / "qa_report.txt"
    rep.write_text(f"Проверено: {total}, проблем: {bad}\n" + "\n".join(lines) + "\n",
                   encoding="utf-8")
    print(f"Отчёт: {rep}")


if __name__ == "__main__":
    main()
