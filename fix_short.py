#!/usr/bin/env python3
"""Добивка 10 огрызков: деление EN-чанка пополам + перевод с большим лимитом токенов."""
import os
import re
import sys
import time
from pathlib import Path

ROOT = Path("/home/v/projects/Чарак Самхита")
RED_BREAD_ENV = Path("/home/v/projects/Красный хлеб/.env")
PART_DIR = ROOT / "gemini_full" / "parts"
OUT_DIR = ROOT / "gemini_full" / "out"

STEMS = ["01_Sutra_Sthana.13_Sneha.p02", "01_Sutra_Sthana.23_Santarpaniya.p04",
         "04_Sharira_Sthana.06_Sharira_Vichaya_Sharira.p02",
         "04_Sharira_Sthana.08_Jatisutriya_Sharira.p04",
         "06_Chikitsa_Sthana.06_Prameha_Chikitsa.p02",
         "06_Chikitsa_Sthana.11_Kshatakshina_Chikitsa.p02",
         "06_Chikitsa_Sthana.23_Visha_Chikitsa.p04",
         "06_Chikitsa_Sthana.25_Dwivraniya_Chikitsa.p02",
         "06_Chikitsa_Sthana.25_Dwivraniya_Chikitsa.p03",
         "08_Siddhi_Sthana.06_Vamana_Virechana_Vyapat_Siddhi.p02"]

SYSTEM = ("Ты — профессиональный переводчик аюрведических текстов с английского на русский. "
          "Переводишь Чарак Самхиту. Стиль: точный книжный русский, без отсебятины. "
          "Сохраняй markdown-структуру и разбивку на абзацы один в один. "
          "Санскритские термины давай в русских кавычках «...», подчёркивания _ запрещены. "
          "Переведи ВЕСЬ отрывок целиком до конца, ничего не сокращай. Только перевод.")
TMPL = "Переведи ВЕСЬ следующий отрывок Чарак Самхиты на русский целиком, до конца. Только перевод:\n\n{text}"
MODELS = [m.strip() for m in os.environ.get(
    "GEMINI_MODELS",
    "gemini-3.8-flash,gemini-3.1-flash-lite,gemini-3.7-flash,gemini-3.5-flash").split(",") if m.strip()]


def load_client():
    key = os.environ.get("GEMINI_API_KEY")
    if not key and RED_BREAD_ENV.exists():
        for line in RED_BREAD_ENV.read_text().splitlines():
            if line.startswith("GEMINI_API_KEY"):
                key = line.split("=", 1)[1].strip().strip('"').strip("'")
    if not key:
        sys.exit("нет ключа")
    from google import genai
    return genai.Client(api_key=key)


def tr(client, text, tag):
    for att in range(1, 9):
        model = MODELS[(att - 1) % len(MODELS)]
        try:
            resp = client.models.generate_content(
                model=model, contents=TMPL.format(text=text),
                config={"system_instruction": SYSTEM, "temperature": 0.3,
                        "max_output_tokens": 32768})
            ru = (resp.text or "").strip()
            if not ru:
                raise RuntimeError("пустой ответ")
            print(f"  [{tag}] {model}: {len(ru.split())} слов", flush=True)
            return ru
        except Exception as e:
            wait = min(30 * att, 300)
            print(f"  [{tag}] {model} п{att}: {type(e).__name__} {str(e)[:80]}; жду {wait}с", flush=True)
            time.sleep(wait)
    raise RuntimeError(f"не перевёлся {tag}")


def main():
    client = load_client()
    for stem in STEMS:
        dest = OUT_DIR / f"{stem}.ru.txt"
        if dest.exists() and dest.read_text(encoding="utf-8").strip():
            print(f"[{stem}] уже есть — пропуск", flush=True)
            continue
        paras = [p for p in re.split(r"\n\s*\n",
                 (PART_DIR / f"{stem}.en.txt").read_text(encoding="utf-8")) if p.strip()]
        mid, acc = len(paras) // 2, 0
        # баланс по словам, не по числу абзацев
        words = [len(p.split()) for p in paras]
        total = sum(words)
        cut, acc = 0, 0
        for i, w in enumerate(words):
            acc += w
            if acc >= total / 2:
                cut = i + 1
                break
        halves = ["\n\n".join(paras[:cut]), "\n\n".join(paras[cut:])]
        print(f"[{stem}] EN {total} слов → половины {len(halves[0].split())}+{len(halves[1].split())}",
              flush=True)
        ru = "\n\n".join(tr(client, h, f"{stem}.h{k + 1}") for k, h in enumerate(halves))
        dest.write_text(ru + "\n", encoding="utf-8")
        print(f"[{stem}] СОБРАН: {len(ru.split())} слов", flush=True)
        time.sleep(20)


if __name__ == "__main__":
    main()
