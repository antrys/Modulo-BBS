I'll build this with two built-in bitmap fonts plus scaling, so you get real size variety rather than one fixed look.

Ran 2 commands, created a file, read a file · 1 note

Two hand-built bitmap fonts (3×5 and 5×7, covering A–Z, 0–9, and ~30 punctuation marks) with integer scaling on top, which gives you six size presets plus arbitrary scaling.

```bash
python3 blockletters.py "hello world"          # medium (default)
python3 blockletters.py -s tiny "compact"      # 5 rows tall
python3 blockletters.py -s giant "BIG"         # 42 rows tall
python3 blockletters.py --scale 5 "custom"     # any factor 1-20
python3 blockletters.py --all "demo"           # every size at once
```
Other flags worth knowing:
```bash
--fill '█' — swap the ink character (--blank for the background)
-w 80 or -w 0 — wrap to a column count, or to your terminal width
-b — draw a box around it
-f 3x5 — force a font independent of the size preset
--spacing 2 — widen the gap between letters
Piping works too: echo "text" | python3 blockletters.py -s large
```
Unknown characters render as ? rather than crashing, and input is case-insensitive. If you want to use it as a library, render("text", size="large", fill="*") returns the string directly.
