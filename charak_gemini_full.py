#!/usr/bin/env python3
"""Полный перевод Чарак Самхиты через Gemini — по примеру Красного хлеба.

Корпус: /home/v/mimocode/charak_english/<Sthana>/<Adhyaya>.txt (8 стхан, 120 файлов,
без вложенного charak_samhita_english_only/).

Стадии:
  split  — режет ВСЕ файлы на чанки по абзацам (без API)
  run    — переводит недостающие чанки (resume, rate-limit, retry)
  merge  — собирает русские файлы из чанков
  status — прогресс по стханам
"""
import argparse
import json
import os
import re
import sys
import time
from pathlib import Path

ROOT = Path("/home/v/projects/Чарак Самхита")
SRC_ROOT = Path("/home/v/mimocode/charak_english")
RED_BREAD_ENV = Path("/home/v/projects/Красный хлеб/.env")
WORK = ROOT / "gemini_full"
PART_DIR = WORK / "parts"
OUT_DIR = WORK / "out"
MANIFEST = WORK / "manifest.json"
RU_ROOT = ROOT / "ru"

STHANAS = ["01_Sutra_Sthana", "02_Nidana_Sthana", "03_Vimana_Sthana",
           "04_Sharira_Sthana", "05_Indriya_Sthana", "06_Chikitsa_Sthana",
           "07_Kalpa_Sthana", "08_Siddhi_Sthana"]

SYSTEM = (
    "Ты — профессиональный переводчик аюрведических текстов с английского на русский. "
    "Переводишь Чарак Самхиту (английский перевод с санскрита, издание carakasamhitaonline). "
    "Стиль: точный книжный русский, живой но без отсебятины. "
    "Сохраняй markdown-структуру один в один (## заголовки, списки * ...). "
    "Санскритские термины в подчёркиваниях _..._ переводи в русские кавычки «...» "
    "(вата, питта, капха, доша, унмада и т.п.: _доша_ → «доша»), при первом появлении допустим перевод в скобках. "
    "Никогда не оставляй нижние подчёркивания _ в переводе. "
    "Разбивку на абзацы сохраняй один в один. Только текст перевода, без пояснений."
)
PROMPT_TMPL = "Переведи следующий отрывок Чарак Самхиты на русский. Только перевод:\n\n{text}"

CHUNK_WORDS = 3500
SLEEP_OK = 7.0
MAX_RETRIES = 8
MAX_ROUNDS = 6


def iter_sources():
    files = []
    for st in STHANAS:
        d = SRC_ROOT / st
        if not d.exists():
            continue
        for f in sorted(d.glob("*.txt")):
            files.append((st, f))
    return files


def stem_of(sthana, path):
    return f"{sthana}.{path.stem}"


def cmd_split(_args):
    PART_DIR.mkdir(parents=True, exist_ok=True)
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    manifest = {"files": [], "chunk_words": CHUNK_WORDS}
    total_parts, total_words = 0, 0
    for sthana, src in iter_sources():
        text = src.read_text(encoding="utf-8")
        stem = stem_of(sthana, src)
        paras = [p for p in re.split(r"\n\s*\n", text) if p.strip()]
        parts, cur, words = [], [], 0
        for p in paras:
            w = len(p.split())
            if cur and words + w > CHUNK_WORDS:
                parts.append("\n\n".join(cur))
                cur, words = [], 0
            cur.append(p)
            words += w
        if cur:
            parts.append("\n\n".join(cur))
        for kk, chunk in enumerate(parts, 1):
            (PART_DIR / f"{stem}.p{kk:02d}.en.txt").write_text(chunk + "\n", encoding="utf-8")
        manifest["files"].append({"sthana": sthana, "src": src.name,
                                  "stem": stem, "parts": len(parts),
                                  "words_en": len(text.split())})
        total_parts += len(parts)
        total_words += len(text.split())
        print(f"{stem}: {len(parts)} чанков, {len(text.split())} слов")
    MANIFEST.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"ИТОГО: {len(manifest['files'])} файлов, {total_parts} чанков, {total_words} слов")


def _load_client():
    api_key = os.environ.get("GEMINI_API_KEY")
    for env_file in (RED_BREAD_ENV, ROOT / ".env"):
        if not api_key and env_file.exists():
            for line in env_file.read_text().splitlines():
                if line.startswith("GEMINI_API_KEY"):
                    api_key = line.split("=", 1)[1].strip().strip('"').strip("'")
                    break
    if not api_key:
        sys.exit("ОШИБКА: нет GEMINI_API_KEY")
    from google import genai
    return genai.Client(api_key=api_key)


def cmd_run(args):
    if not MANIFEST.exists():
        sys.exit("ОШИБКА: сначала выполни split")
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    models = [m.strip() for m in os.environ.get(
        "GEMINI_MODELS",
        "gemini-3.8-flash,gemini-3.1-flash-lite,gemini-3.7-flash,gemini-3.5-flash",
    ).split(",") if m.strip()]
    print(f"Модели: {', '.join(models)}", flush=True)
    all_stems = [f"{f['stem']}.p{kk:02d}" for f in manifest["files"]
                 for kk in range(1, f["parts"] + 1)]
    todo = [p for p in all_stems if not (OUT_DIR / f"{p}.ru.txt").exists()
            or not (OUT_DIR / f"{p}.ru.txt").read_text(encoding="utf-8").strip()]
    done = len(all_stems) - len(todo)
    if args.limit:
        todo = todo[:args.limit]
    print(f"Всего {len(all_stems)}, готово {done}, к работе {len(todo)}", flush=True)
    if not todo:
        print("Переводить нечего — выполни merge")
        return
    client = _load_client()
    from google.genai import errors

    def try_chunk(pstem):
        text = (PART_DIR / f"{pstem}.en.txt").read_text(encoding="utf-8")
        prompt = PROMPT_TMPL.format(text=text)
        for attempt in range(1, MAX_RETRIES + 1):
            model = models[(attempt - 1) % len(models)]
            try:
                resp = client.models.generate_content(
                    model=model, contents=prompt,
                    config={"system_instruction": SYSTEM, "temperature": 0.3},
                )
                ru = (resp.text or "").strip()
                if not ru:
                    raise RuntimeError("пустой ответ")
                tmp = OUT_DIR / f"{pstem}.ru.txt.tmp"
                tmp.write_text(ru + "\n", encoding="utf-8")
                tmp.replace(OUT_DIR / f"{pstem}.ru.txt")
                print(f"  [{pstem}]: {len(ru.split())} слов ({model})", flush=True)
                return True
            except Exception as e:
                wait = min(15 * attempt, 120)
                print(f"  [{pstem}] {model} попытка {attempt}/{MAX_RETRIES}: "
                      f"{type(e).__name__}: {str(e)[:100]}; жду {wait}с", flush=True)
                time.sleep(wait)
        return False

    pending = todo
    for rnd in range(1, MAX_ROUNDS + 1):
        if rnd > 1:
            print(f"=== Раунд {rnd}: {len(pending)} чанков, пауза 60с ===", flush=True)
            time.sleep(60)
        failed = []
        for pstem in pending:
            if not try_chunk(pstem):
                failed.append(pstem)
            time.sleep(SLEEP_OK)
        pending = failed
        if not pending:
            break
    left = sum(1 for p in all_stems if not (OUT_DIR / f"{p}.ru.txt").exists())
    if pending:
        sys.exit(f"ОШИБКА: {len(pending)} чанков не переведено: {pending[:5]} (повтори run)")
    print(f"Готово. Осталось: {left}" + (" — повтори run" if left else " — выполни merge"))


def norm_quotes(s):
    """_термин_ → «термин»: подчёркивания ужасны при озвучке, кавычки читаются чисто."""
    return re.sub(r"(?<!_)_(?!_)([^_\n*]+?)(?<!_)_(?!_)", r"«\1»", s)


def cmd_merge(_args):
    if not MANIFEST.exists():
        sys.exit("ОШИБКА: сначала выполни split")
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    done, missing = 0, []
    for f in manifest["files"]:
        out = []
        for kk in range(1, f["parts"] + 1):
            p = OUT_DIR / f"{f['stem']}.p{kk:02d}.ru.txt"
            if not p.exists():
                missing.append(p.name)
                continue
            out.append(norm_quotes(p.read_text(encoding="utf-8").strip()))
        if len(out) == f["parts"]:
            dest = RU_ROOT / f["sthana"] / f"{Path(f['src']).stem}.ru.txt"
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_text("\n\n".join(out), encoding="utf-8")
            done += 1
    print(f"Собрано файлов: {done}/{len(manifest['files'])}" +
          (f", не хватает чанков: {len(missing)} {missing[:3]}" if missing else ""))


def cmd_status(_args):
    if not MANIFEST.exists():
        print("split ещё не выполнялся")
        return
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    total = done = 0
    by_sthana = {}
    for f in manifest["files"]:
        d = sum(1 for kk in range(1, f["parts"] + 1)
                if (OUT_DIR / f"{f['stem']}.p{kk:02d}.ru.txt").exists())
        total += f["parts"]
        done += d
        s = by_sthana.setdefault(f["sthana"], [0, 0])
        s[0] += d
        s[1] += f["parts"]
    for st in STHANAS:
        if st in by_sthana:
            d, t = by_sthana[st]
            print(f"{st}: {d}/{t}" + (" ✓" if d == t else ""))
    print(f"ИТОГО: {done}/{total} чанков")
    n_ru = len(list(RU_ROOT.rglob("*.ru.txt"))) if RU_ROOT.exists() else 0
    print(f"RU-файлов собрано: {n_ru}")


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("split")
    run = sub.add_parser("run")
    run.add_argument("--limit", type=int, default=0)
    sub.add_parser("merge")
    sub.add_parser("status")
    args = ap.parse_args()
    {"split": cmd_split, "run": cmd_run, "merge": cmd_merge, "status": cmd_status}[args.cmd](args)


if __name__ == "__main__":
    main()
