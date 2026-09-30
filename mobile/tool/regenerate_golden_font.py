#!/usr/bin/env python3
"""Regenerate the deterministic Flutter golden CJK font subset.

This font is test-only. It is never bundled in the production app.
"""

from __future__ import annotations

import argparse
import hashlib
import pathlib
import subprocess
import sys
import tempfile
import urllib.request
import unicodedata

ROOT = pathlib.Path(__file__).resolve().parents[1]
PINNED_COMMIT = "523d033d6cb47f4a80c58a35753646f5c3608a78"
SOURCE_URL = (
    "https://raw.githubusercontent.com/notofonts/noto-cjk/"
    + PINNED_COMMIT
    + "/Sans/Variable/TTF/Subset/NotoSansSC-VF.ttf"
)
OUTPUT = ROOT / "test/fonts/JiYiGoldenCJK-Regular.ttf"


def visible_corpus() -> str:
    chars: set[str] = {chr(code) for code in range(0x20, 0x7F)}
    paths = list((ROOT / "lib").rglob("*.dart"))
    paths.extend((ROOT / "test").rglob("*.dart"))
    for path in paths:
        text = path.read_text(encoding="utf-8")
        chars.update(
            ch for ch in text
            if not unicodedata.category(ch).startswith("C")
        )
    return "".join(sorted(chars, key=ord))


def run(*args: str) -> None:
    subprocess.run(args, check=True)


def regenerate() -> str:
    try:
        import fontTools  # noqa: F401
    except ImportError as exc:
        raise SystemExit(
            "fonttools is required: pip install fonttools==4.59.2"
        ) from exc

    with tempfile.TemporaryDirectory(prefix="jiyi-golden-font-") as raw_tmp:
        tmp = pathlib.Path(raw_tmp)
        variable = tmp / "NotoSansSC-VF.ttf"
        regular = tmp / "NotoSansSC-Regular.ttf"
        corpus_file = tmp / "corpus.txt"

        urllib.request.urlretrieve(SOURCE_URL, variable)
        corpus_file.write_text(visible_corpus(), encoding="utf-8")

        run(
            sys.executable,
            "-m",
            "fontTools.varLib.instancer",
            str(variable),
            "wght=400",
            "--output",
            str(regular),
        )
        run(
            sys.executable,
            "-m",
            "fontTools.subset",
            str(regular),
            "--text-file=" + str(corpus_file),
            "--output-file=" + str(OUTPUT),
            "--layout-features=*",
            "--name-IDs=*",
            "--name-legacy",
            "--name-languages=*",
            "--glyph-names",
            "--symbol-cmap",
            "--legacy-cmap",
            "--notdef-glyph",
            "--notdef-outline",
            "--recommended-glyphs",
        )

    digest = hashlib.sha256(OUTPUT.read_bytes()).hexdigest()
    print(f"golden font: {OUTPUT}")
    print(f"sha256: {digest}")
    return digest


def verify_coverage() -> None:
    from fontTools.ttLib import TTFont

    font = TTFont(OUTPUT)
    cmap = font.getBestCmap() or {}
    missing = sorted({ord(ch) for ch in visible_corpus()} - set(cmap))
    if missing:
        preview = " ".join(f"U+{code:04X}" for code in missing[:40])
        raise SystemExit(
            f"golden font missing {len(missing)} codepoints: {preview}"
        )
    print(f"coverage PASS: {len(cmap)} mapped codepoints")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    if not args.check:
        regenerate()
    verify_coverage()


if __name__ == "__main__":
    main()
