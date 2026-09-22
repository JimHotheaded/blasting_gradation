# Repository Guidelines

Project instructions live in **`CLAUDE.md`**. Read it before changing anything:
it holds the pipeline description, the calculation and export contracts, and the
deliberate choices that should not be "corrected" without asking.

Quick reference, from the repository root:

```powershell
.\.venv\Scripts\python.exe -B -m unittest discover -s tests -v
.\.venv\Scripts\python.exe -B rock_gradation.py <photo> --roi <x,y,w,h> --overlay-format png --out output/<YYYY-MM-DD>
```

Site photos (`stockpile_picture/`), generated reports (`output/`), the
virtualenv and model weights are deliberately untracked.
