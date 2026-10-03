#!/usr/bin/env python3
"""Сборка всего русского перевода в один PDF с оглавлением.

Вход: ru/<Sthana>/<Adhyaya>.ru.txt (120 файлов, лёгкий markdown)
Выход: charak_samhita_ru_full.pdf
Шрифты DejaVu (кириллица из коробки).
"""
import html
import re
from pathlib import Path

from reportlab.lib.pagesizes import A5
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (BaseDocTemplate, Frame, PageBreak, PageTemplate,
                                Paragraph, Spacer)
from reportlab.platypus.tableofcontents import TableOfContents

ROOT = Path("/home/v/projects/Чарак Самхита")
RU = ROOT / "ru"
OUT = ROOT / "charak_samhita_ru_full.pdf"
FD = "/usr/share/fonts/truetype/dejavu/"

STHANA_RU = {"01_Sutra_Sthana": "Сутра Стхана", "02_Nidana_Sthana": "Нидана Стхана",
             "03_Vimana_Sthana": "Вимана Стхана", "04_Sharira_Sthana": "Шарира Стхана",
             "05_Indriya_Sthana": "Индрия Стхана", "06_Chikitsa_Sthana": "Чикитса Стхана",
             "07_Kalpa_Sthana": "Калпа Стхана", "08_Siddhi_Sthana": "Сиддхи Стхана"}
STHANAS = list(STHANA_RU)


def adhyaya_title(stem):
    return stem.split("_", 1)[1].replace("_", " ") if "_" in stem else stem


class Doc(BaseDocTemplate):
    def afterFlowable(self, flowable):
        if isinstance(flowable, Paragraph):
            lvl = getattr(flowable, "_toc_level", None)
            if lvl is not None:
                self.notify("TOCEntry", (lvl, flowable.getPlainText(), self.page))


def build():
    pdfmetrics.registerFont(TTFont("Serif", FD + "DejaVuSerif.ttf"))
    pdfmetrics.registerFont(TTFont("Serif-B", FD + "DejaVuSerif-Bold.ttf"))
    pdfmetrics.registerFont(TTFont("Serif-I", FD + "DejaVuSerif-Italic.ttf"))
    pdfmetrics.registerFont(TTFont("Sans", FD + "DejaVuSans.ttf"))
    pdfmetrics.registerFont(TTFont("Sans-B", FD + "DejaVuSans-Bold.ttf"))

    ss = getSampleStyleSheet()
    body = ParagraphStyle("body", parent=ss["Normal"], fontName="Serif", fontSize=9,
                          leading=13, spaceAfter=4, alignment=4)
    h1 = ParagraphStyle("h1", fontName="Sans-B", fontSize=16, leading=20,
                        spaceBefore=10, spaceAfter=8, keepWithNext=True)
    h2 = ParagraphStyle("h2", fontName="Sans-B", fontSize=12, leading=16,
                        spaceBefore=8, spaceAfter=6, keepWithNext=True)
    h3 = ParagraphStyle("h3", fontName="Sans-B", fontSize=10.5, leading=14,
                        spaceBefore=6, spaceAfter=4, keepWithNext=True)
    bullet = ParagraphStyle("bullet", parent=body, leftIndent=12, firstLineIndent=0,
                            bulletIndent=4, spaceAfter=3)
    title = ParagraphStyle("title", fontName="Sans-B", fontSize=26, leading=32,
                           alignment=1, spaceAfter=10)
    subtitle = ParagraphStyle("subtitle", fontName="Serif", fontSize=12, leading=16,
                              alignment=1, spaceAfter=4)
    toc_head = ParagraphStyle("tochead", fontName="Sans-B", fontSize=16, leading=20,
                              spaceAfter=8)
    toc_lvl0 = ParagraphStyle("toc0", fontName="Sans-B", fontSize=10, leading=14)
    toc_lvl1 = ParagraphStyle("toc1", fontName="Serif", fontSize=9, leading=13,
                              leftIndent=12)

    doc = Doc(str(OUT), pagesize=A5, leftMargin=15 * mm, rightMargin=13 * mm,
              topMargin=15 * mm, bottomMargin=15 * mm,
              title="Чарак Самхита — русский перевод", author="Перевод Gemini,Montazh opencode")
    frame = Frame(doc.leftMargin, doc.bottomMargin, doc.width, doc.height, id="f")
    doc.addPageTemplates([PageTemplate(id="p", frames=[frame])])

    story = []
    story.append(Spacer(1, 60))
    story.append(Paragraph("Чарак Самхита", title))
    story.append(Paragraph("Полный русский перевод с английского издания (carakasamhitaonline)", subtitle))
    story.append(Paragraph("Переведено через Gemini по конвейеру проекта «Красный хлеб». "
                           "Санскритские термины — в кавычках-ёлочках для чистого чтения вслух.",
                           subtitle))
    story.append(PageBreak())
    t = Paragraph("Содержание", toc_head)
    t._toc_level = None
    story.append(t)
    toc = TableOfContents()
    toc.levelStyles = [toc_lvl0, toc_lvl1]
    story.append(toc)
    story.append(PageBreak())

    def HP(text, style, lvl):
        p = Paragraph(html.escape(text), style)
        p._toc_level = lvl
        return p

    for st in STHANAS:
        d = RU / st
        files = sorted(d.glob("*.ru.txt"))
        if not files:
            continue
        story.append(HP(STHANA_RU[st], h1, 0))
        for f in files:
            name = adhyaya_title(f.stem.replace(".ru", ""))
            story.append(HP(name, h2, 1))
            for raw in f.read_text(encoding="utf-8").splitlines():
                s = raw.strip()
                if not s:
                    story.append(Spacer(1, 3))
                    continue
                if s.startswith("## "):
                    story.append(HP(s[3:].strip("# "), h2, 1))
                elif s.startswith("### "):
                    story.append(Paragraph(html.escape(s[4:].strip("# ")), h3))
                elif re.match(r"^\*(\s|$)", s):
                    story.append(Paragraph(html.escape(re.sub(r"^\*\s*", "", s)), bullet,
                                           bulletText="•"))
                else:
                    story.append(Paragraph(html.escape(s), body))

    doc.multiBuild(story)
    print(f"Готово: {OUT} ({OUT.stat().st_size // 1024} KB)")


if __name__ == "__main__":
    build()
