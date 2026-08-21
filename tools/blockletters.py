#!/usr/bin/env python3
"""
blockletters.py - Render a phrase as ASCII block letters at various sizes.

Examples:
    python3 blockletters.py "hello world"
    python3 blockletters.py -s large "BIG"
    python3 blockletters.py -s tiny --fill '*' "small"
    python3 blockletters.py --scale 5 "huge"
    python3 blockletters.py --all "sizes"
    python3 blockletters.py --border -w 60 "wraps onto multiple lines"
"""

import argparse
import shutil
import sys

# ---------------------------------------------------------------------------
# Fonts: each glyph is a list of rows of '#' (ink) and '.' (blank)
# ---------------------------------------------------------------------------

def _f(spec):
    """Parse a compact 'row/row/row' spec into a list of rows."""
    return spec.split("/")


FONT_3x5 = {
    "A": _f(".#./#.#/###/#.#/#.#"),
    "B": _f("##./#.#/##./#.#/##."),
    "C": _f(".##/#../#../#../.##"),
    "D": _f("##./#.#/#.#/#.#/##."),
    "E": _f("###/#../##./#../###"),
    "F": _f("###/#../##./#../#.."),
    "G": _f(".##/#../#.#/#.#/.##"),
    "H": _f("#.#/#.#/###/#.#/#.#"),
    "I": _f("###/.#./.#./.#./###"),
    "J": _f("..#/..#/..#/#.#/.#."),
    "K": _f("#.#/#.#/##./#.#/#.#"),
    "L": _f("#../#../#../#../###"),
    "M": _f("#.#/###/###/#.#/#.#"),
    "N": _f("#.#/##./###/.##/#.#"),
    "O": _f(".#./#.#/#.#/#.#/.#."),
    "P": _f("##./#.#/##./#../#.."),
    "Q": _f(".#./#.#/#.#/##./.##"),
    "R": _f("##./#.#/##./#.#/#.#"),
    "S": _f(".##/#../.#./..#/##."),
    "T": _f("###/.#./.#./.#./.#."),
    "U": _f("#.#/#.#/#.#/#.#/###"),
    "V": _f("#.#/#.#/#.#/#.#/.#."),
    "W": _f("#.#/#.#/###/###/#.#"),
    "X": _f("#.#/#.#/.#./#.#/#.#"),
    "Y": _f("#.#/#.#/.#./.#./.#."),
    "Z": _f("###/..#/.#./#../###"),
    "0": _f("###/#.#/#.#/#.#/###"),
    "1": _f(".#./##./.#./.#./###"),
    "2": _f("##./..#/.#./#../###"),
    "3": _f("##./..#/.#./..#/##."),
    "4": _f("#.#/#.#/###/..#/..#"),
    "5": _f("###/#../##./..#/##."),
    "6": _f("###/#../###/#.#/###"),
    "7": _f("###/..#/.#./#../#.."),
    "8": _f("###/#.#/###/#.#/###"),
    "9": _f("###/#.#/###/..#/###"),
    " ": _f(".../.../.../.../..."),
    ".": _f(".../.../.../.../.#."),
    ",": _f(".../.../.../.#./#.."),
    "!": _f(".#./.#./.#./.../.#."),
    "?": _f("##./..#/.#./.../.#."),
    "'": _f(".#./.#./.../.../..."),
    '"': _f("#.#/#.#/.../.../..."),
    "-": _f(".../.../###/.../..."),
    "+": _f(".../.#./###/.#./..."),
    "=": _f(".../###/.../###/..."),
    "_": _f(".../.../.../.../###"),
    ":": _f(".../.#./.../.#./..."),
    ";": _f(".../.#./.../.#./#.."),
    "/": _f("..#/..#/.#./#../#.."),
    "\\": _f("#../#../.#./..#/..#"),
    "(": _f("..#/.#./.#./.#./..#"),
    ")": _f("#../.#./.#./.#./#.."),
    "[": _f(".##/.#./.#./.#./.##"),
    "]": _f("##./.#./.#./.#./##."),
    "<": _f("..#/.#./#../.#./..#"),
    ">": _f("#../.#./..#/.#./#.."),
    "*": _f("#.#/.#./#.#/.../..."),
    "#": _f("#.#/###/#.#/###/#.#"),
    "@": _f("###/#.#/###/#../.##"),
    "$": _f(".##/##./.#./.##/##."),
    "%": _f("#.#/..#/.#./#../#.#"),
    "&": _f("##./##./###/#.#/###"),
}

FONT_5x7 = {
    "A": _f(".###./#...#/#...#/#####/#...#/#...#/#...#"),
    "B": _f("####./#...#/#...#/####./#...#/#...#/####."),
    "C": _f(".###./#...#/#..../#..../#..../#...#/.###."),
    "D": _f("####./#...#/#...#/#...#/#...#/#...#/####."),
    "E": _f("#####/#..../#..../####./#..../#..../#####"),
    "F": _f("#####/#..../#..../####./#..../#..../#...."),
    "G": _f(".###./#...#/#..../#.###/#...#/#...#/.###."),
    "H": _f("#...#/#...#/#...#/#####/#...#/#...#/#...#"),
    "I": _f("#####/..#../..#../..#../..#../..#../#####"),
    "J": _f("..###/...#./...#./...#./...#./#..#./.##.."),
    "K": _f("#...#/#..#./#.#../##.../#.#../#..#./#...#"),
    "L": _f("#..../#..../#..../#..../#..../#..../#####"),
    "M": _f("#...#/##.##/#.#.#/#.#.#/#...#/#...#/#...#"),
    "N": _f("#...#/##..#/#.#.#/#.#.#/#..##/#...#/#...#"),
    "O": _f(".###./#...#/#...#/#...#/#...#/#...#/.###."),
    "P": _f("####./#...#/#...#/####./#..../#..../#...."),
    "Q": _f(".###./#...#/#...#/#...#/#.#.#/#..#./.##.#"),
    "R": _f("####./#...#/#...#/####./#.#../#..#./#...#"),
    "S": _f(".####/#..../#..../.###./....#/....#/####."),
    "T": _f("#####/..#../..#../..#../..#../..#../..#.."),
    "U": _f("#...#/#...#/#...#/#...#/#...#/#...#/.###."),
    "V": _f("#...#/#...#/#...#/#...#/#...#/.#.#./..#.."),
    "W": _f("#...#/#...#/#...#/#.#.#/#.#.#/##.##/#...#"),
    "X": _f("#...#/#...#/.#.#./..#../.#.#./#...#/#...#"),
    "Y": _f("#...#/#...#/.#.#./..#../..#../..#../..#.."),
    "Z": _f("#####/....#/...#./..#../.#.../#..../#####"),
    "0": _f(".###./#...#/#..##/#.#.#/##..#/#...#/.###."),
    "1": _f("..#../.##../..#../..#../..#../..#../.###."),
    "2": _f(".###./#...#/....#/...#./..#../.#.../#####"),
    "3": _f("#####/...#./..#../...#./....#/#...#/.###."),
    "4": _f("...#./..##./.#.#./#..#./#####/...#./...#."),
    "5": _f("#####/#..../####./....#/....#/#...#/.###."),
    "6": _f("..##./.#.../#..../####./#...#/#...#/.###."),
    "7": _f("#####/....#/...#./..#../.#.../.#.../.#..."),
    "8": _f(".###./#...#/#...#/.###./#...#/#...#/.###."),
    "9": _f(".###./#...#/#...#/.####/....#/...#./.##.."),
    " ": _f("...../...../...../...../...../...../....."),
    ".": _f("...../...../...../...../...../.##../.##.."),
    ",": _f("...../...../...../...../.##../.##../.#..."),
    "!": _f("..#../..#../..#../..#../..#../...../..#.."),
    "?": _f(".###./#...#/....#/...#./..#../...../..#.."),
    "'": _f("..#../..#../...../...../...../...../....."),
    '"': _f(".#.#./.#.#./...../...../...../...../....."),
    "-": _f("...../...../...../#####/...../...../....."),
    "+": _f("...../..#../..#../#####/..#../..#../....."),
    "=": _f("...../...../#####/...../#####/...../....."),
    "_": _f("...../...../...../...../...../...../#####"),
    ":": _f("...../.##../.##../...../.##../.##../....."),
    ";": _f("...../.##../.##../...../.##../.##../.#..."),
    "/": _f("....#/....#/...#./..#../.#.../#..../#...."),
    "\\": _f("#..../#..../.#.../..#../...#./....#/....#"),
    "(": _f("...#./..#../.#.../.#.../.#.../..#../...#."),
    ")": _f(".#.../..#../...#./...#./...#./..#../.#..."),
    "[": _f("..###/..#../..#../..#../..#../..#../..###"),
    "]": _f("###../..#../..#../..#../..#../..#../###.."),
    "<": _f("...#./..#../.#.../#..../.#.../..#../...#."),
    ">": _f(".#.../..#../...#./....#/...#./..#../.#..."),
    "*": _f("...../..#../#.#.#/.###./#.#.#/..#../....."),
    "#": _f(".#.#./.#.#./#####/.#.#./#####/.#.#./.#.#."),
    "@": _f(".###./#...#/#.###/#.#.#/#.###/#..../.###."),
    "$": _f("..#../.####/#.#../.###./..#.#/####./..#.."),
    "%": _f("##.../##..#/...#./..#../.#.../#..##/...##"),
    "&": _f(".##../#..#./#..#./.##../#..#./#...#/.###."),
}

FONTS = {"3x5": FONT_3x5, "5x7": FONT_5x7}

# name -> (font key, scale)
SIZES = {
    "tiny":   ("3x5", 1),
    "small":  ("5x7", 1),
    "medium": ("5x7", 2),
    "large":  ("5x7", 3),
    "huge":   ("5x7", 4),
    "giant":  ("5x7", 6),
}

FALLBACK = "?"


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------

def glyph_for(font, ch):
    """Look up a character, falling back gracefully."""
    ch = ch.upper()
    if ch in font:
        return font[ch]
    return font.get(FALLBACK, font[" "])


def scale_glyph(rows, scale):
    """Blow a glyph up by an integer factor in both directions."""
    if scale == 1:
        return list(rows)
    out = []
    for row in rows:
        wide = "".join(c * scale for c in row)
        out.extend([wide] * scale)
    return out


def render_word(text, font, scale, spacing):
    """Render text as a list of pattern rows ('#'/'.'), no wrapping."""
    if not text:
        return []
    glyphs = [scale_glyph(glyph_for(font, c), scale) for c in text]
    height = len(glyphs[0])
    gap = "." * spacing
    return [gap.join(g[r] for g in glyphs) for r in range(height)]


def wrap_text(text, font, scale, spacing, max_width):
    """Split text into lines that fit within max_width columns."""
    if not max_width:
        return [text]

    char_w = len(next(iter(font.values()))[0]) * scale

    def width_of(s):
        if not s:
            return 0
        return len(s) * char_w + (len(s) - 1) * spacing

    lines, current = [], ""
    for word in text.split(" "):
        candidate = word if not current else current + " " + word
        if width_of(candidate) <= max_width or not current:
            current = candidate
        else:
            lines.append(current)
            current = word
    if current:
        lines.append(current)
    return lines


def paint(rows, fill, blank):
    """Convert '#'/'.' pattern rows into final display rows."""
    return [r.replace("#", fill).replace(".", blank) for r in rows]


def add_border(lines, pad=1):
    """Wrap rendered lines in a box."""
    width = max((len(l) for l in lines), default=0)
    body = [l.ljust(width) for l in lines]
    padding = " " * pad
    inner = width + pad * 2
    out = ["+" + "-" * inner + "+"]
    out.append("|" + " " * inner + "|")
    out += ["|" + padding + l + padding + "|" for l in body]
    out.append("|" + " " * inner + "|")
    out.append("+" + "-" * inner + "+")
    return out


def render(text, size=None, font_key=None, scale=None, fill="#", blank=" ",
           spacing=1, max_width=None, border=False, line_gap=1):
    """Render text into a single printable string."""
    if size:
        base_font, base_scale = SIZES[size]
    else:
        base_font, base_scale = "5x7", 1
    font = FONTS[font_key or base_font]
    scale = scale if scale is not None else base_scale

    out_rows = []
    text_lines = wrap_text(text, font, scale, spacing, max_width)
    for i, line in enumerate(text_lines):
        if i:
            out_rows.extend([""] * line_gap)
        out_rows.extend(render_word(line, font, scale, spacing))

    painted = paint(out_rows, fill, blank)
    painted = [p.rstrip() for p in painted]
    if border:
        painted = add_border(painted)
    return "\n".join(painted)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def build_parser():
    p = argparse.ArgumentParser(
        prog="blockletters",
        description="Render a phrase as ASCII block letters at various sizes.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "sizes: " + ", ".join(f"{k} ({f}, x{s})" for k, (f, s) in SIZES.items())
            + "\n\nexamples:\n"
            "  blockletters.py \"hello world\"\n"
            "  blockletters.py -s large \"BIG\"\n"
            "  blockletters.py --scale 5 --fill '*' \"stars\"\n"
            "  blockletters.py --all \"demo\"\n"
        ),
    )
    p.add_argument("phrase", nargs="*", help="text to render")
    p.add_argument("-s", "--size", choices=list(SIZES), default="medium",
                   help="named size preset (default: medium)")
    p.add_argument("-f", "--font", choices=list(FONTS),
                   help="override the base font of the size preset")
    p.add_argument("-x", "--scale", type=int,
                   help="override the scale multiplier (1-20)")
    p.add_argument("--fill", default="#", metavar="CHAR",
                   help="character used for the ink (default: #)")
    p.add_argument("--blank", default=" ", metavar="CHAR",
                   help="character used for empty space (default: space)")
    p.add_argument("--spacing", type=int, default=1, metavar="N",
                   help="columns between letters, pre-scaling (default: 1)")
    p.add_argument("-w", "--width", type=int, metavar="COLS",
                   help="wrap to this many columns (use 0 for terminal width)")
    p.add_argument("-b", "--border", action="store_true",
                   help="draw a box around the output")
    p.add_argument("--all", action="store_true",
                   help="render the phrase at every named size")
    p.add_argument("--list-sizes", action="store_true",
                   help="list the available size presets and exit")
    return p


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.list_sizes:
        for name, (fk, sc) in SIZES.items():
            font = FONTS[fk]
            h = len(next(iter(font.values()))) * sc
            print(f"{name:<8} font={fk} scale={sc} height={h} rows")
        return 0

    phrase = " ".join(args.phrase)
    if not phrase:
        if not sys.stdin.isatty():
            phrase = sys.stdin.read().strip()
        if not phrase:
            parser.print_help()
            return 1

    if args.scale is not None and not (1 <= args.scale <= 20):
        parser.error("--scale must be between 1 and 20")

    if args.fill == "" or args.blank == "":
        parser.error("--fill and --blank need at least one character")

    max_width = args.width
    if max_width == 0:
        max_width = shutil.get_terminal_size((80, 24)).columns
    if max_width is not None and max_width < 5:
        parser.error("--width must be at least 5")

    common = dict(
        fill=args.fill,
        blank=args.blank,
        spacing=args.spacing,
        max_width=max_width,
        border=args.border,
    )

    if args.all:
        for name in SIZES:
            print(f"--- {name} ---")
            print(render(phrase, size=name, **common))
            print()
    else:
        print(render(phrase, size=args.size, font_key=args.font,
                     scale=args.scale, **common))
    return 0


if __name__ == "__main__":
    sys.exit(main())
