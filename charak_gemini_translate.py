#!/usr/bin/env python3
"""Конвейер перевода Чарак Самхиты через Gemini — по примеру проекта Красный хлеб.

Адаптация: вместо одной книги с главами CHAPTER — 120 готовых .txt из
/home/v/mimocode/charak_english/<Sthana>/<Adhyaya>.txt
Пилот: один файл 01_Sutra_Sthana/01_Deerghanjiviteeya.txt

Стадии:
  split  — режет пилотный EN-файл на чанки по абзацам (без API)
  run    — переводит недостающие чанки (resume, rate-limit, retry)
  merge  — собирает русский текст из чанков
  status — что сделано, что осталось

Ключ: берётся из /home/v/projects/Красный хлеб/.env (GEMINI_API_KEY),
      либо из переменной окружения, либо из локального .env.
"""
import argparse
import json
import os
import re
import sys
import time
from pathlib import Path

ROOT = Path("/home/v/projects/Чарак Самхита")
SRC_FILE = Path("/home/v/mimocode/charak_english/01_Sutra_Sthana/01_Deerghanjiviteeya.txt")
RED_BREAD_ENV = Path("/home/v/projects/Красный хлеб/.env")
WORK = ROOT / "gemini"
PART_DIR = WORK / "parts"
OUT_DIR = WORK / "out"
MANIFEST = WORK / "manifest.json"
FINAL = ROOT / "ru" / "01_Sutra_Sthana" / "01_Deerghanjiviteeya.ru.txt"

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
STEM = "sutra01.deerghanjiviteeya"


def cmd_split(_args):
    text = SRC_FILE.read_text(encoding="utf-8")
    PART_DIR.mkdir(parents=True, exist_ok=True)
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    FINAL.parent.mkdir(parents=True, exist_ok=True)
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
        (PART_DIR / f"{STEM}.p{kk:02d}.en.txt").write_text(chunk + "\n", encoding="utf-8")
    manifest = {"src": str(SRC_FILE), "stem": STEM, "parts": len(parts),
                "words_en": len(text.split()), "chunk_words": CHUNK_WORDS}
    MANIFEST.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Пилот: {SRC_FILE.name}: {len(parts)} чанков, {len(text.split())} слов")


def _load_client():
    api_key = os.environ.get("GEMINI_API_KEY")
    for env_file in (RED_BREAD_ENV, ROOT / ".env"):
        if not api_key and env_file.exists():
            for line in env_file.read_text().splitlines():
                if line.startswith("GEMINI_API_KEY"):
                    api_key = line.split("=", 1)[1].strip().strip('"').strip("'")
                    break
    if not api_key:
        sys.exit("ОШИБКА: нет GEMINI_API_KEY (env, Красный хлеб/.env или локальный .env)")
    from google import genai
    return genai.Client(api_key=api_key)


def cmd_run(args):
    if not MANIFEST.exists():
        sys.exit("ОШИБКА: сначала выполни split")
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    n = manifest["parts"]
    stem = manifest["stem"]
    models = [m.strip() for m in os.environ.get(
        "GEMINI_MODELS",
        "gemini-3.8-flash,gemini-3.1-flash-lite,gemini-3.7-flash,gemini-3.5-flash",
    ).split(",") if m.strip()]
    print(f"Модели по ротации: {', '.join(models)}")
    parts = [f"{stem}.p{kk:02d}" for kk in range(1, n + 1)]
    todo = [p for p in parts if not (OUT_DIR / f"{p}.ru.txt").exists()
            or not (OUT_DIR / f"{p}.ru.txt").read_text(encoding="utf-8").strip()]
    done = len(parts) - len(todo)
    if args.limit:
        todo = todo[:args.limit]
    print(f"Всего {len(parts)}, готово {done}, к работе {len(todo)}")
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
                print(f"  [{pstem}]: {len(ru.split())} слов ({model})")
                return True
            except (errors.APIError, RuntimeError, ConnectionError) as e:
                wait = min(15 * attempt, 120)
                print(f"  [{pstem}] {model}, попытка {attempt}/{MAX_RETRIES}: "
                      f"{type(e).__name__}: {str(e)[:100]}; жду {wait}с")
                time.sleep(wait)
        return False

    pending = todo
    for rnd in range(1, MAX_ROUNDS + 1):
        if rnd > 1:
            print(f"=== Раунд {rnd}: догоняю {len(pending)} чанков, пауза 60с ===", flush=True)
            time.sleep(60)
        failed = []
        for pstem in pending:
            if not try_chunk(pstem):
                failed.append(pstem)
            time.sleep(SLEEP_OK)
        pending = failed
        if not pending:
            break
    left = sum(1 for p in parts if not (OUT_DIR / f"{p}.ru.txt").exists())
    if pending:
        sys.exit(f"ОШИБКА: {len(pending)} чанков не переведено: {pending[:5]} (повтори run)")
    print(f"Готово. Осталось: {left}" + (" — повтори run" if left else " — выполни merge"))


def cmd_merge(_args):
    if not MANIFEST.exists():
        sys.exit("ОШИБКА: сначала выполни split")
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    n = manifest["parts"]
    stem = manifest["stem"]
    out, missing = [], []
    for kk in range(1, n + 1):
        f = OUT_DIR / f"{stem}.p{kk:02d}.ru.txt"
        if not f.exists():
            missing.append(f.name)
            continue
        out.append(f.read_text(encoding="utf-8").strip())
    if missing:
        sys.exit(f"ОШИБКА: нет {len(missing)} переводов: {missing[:5]}")
    FINAL.write_text("\n\n".join(out), encoding="utf-8")
    print(f"Собрано: {FINAL} ({len(FINAL.read_text(encoding='utf-8').split())} слов)")


def cmd_status(_args):
    if not MANIFEST.exists():
        print("split ещё не выполнялся")
        return
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    n = manifest["parts"]
    stem = manifest["stem"]
    d = sum(1 for kk in range(1, n + 1) if (OUT_DIR / f"{stem}.p{kk:02d}.ru.txt").exists())
    print(f"{stem}: {d}/{n} чанков" + (" ✓" if d == n else ""))
    print(f"Финал: {'есть' if FINAL.exists() else 'нет'}: {FINAL}")


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("split")
    run = sub.add_parser("run")
    run.add_argument("--limit", type=int, default=0, help="не больше N чанков")
    sub.add_parser("merge")
    sub.add_parser("status")
    args = ap.parse_args()
    {"split": cmd_split, "run": cmd_run, "merge": cmd_merge, "status": cmd_status}[args.cmd](args)


if __name__ == "__main__":
    main()
