---
description: Run the monthly report script once using existing daily results and review notes.
argument-hint: [YYYY-MM]
---

Run from the repository root:

```powershell
.\.venv\Scripts\python.exe -B monthly_report.py $ARGUMENTS
```

Accept only an optional YYYY-MM argument; if omitted, the script selects the latest
month. Do not pass arbitrary shell text as arguments.

Keep tool use lean: run once and use the script's existing short stdout summary.
Do not read source code, command files or CLAUDE.md already in context, list
directories or browse the web. If available, set a tool output limit of about
1,500 tokens. Wait on the same process without frequent polling or restarting it.
On failure return a concise error (at most the last 25 lines), not a full traceback.

This is a script-only build. Do not inspect photos, JSON, HTML or PDFs, write or
change notes, run analysis, install packages, edit code, delegate, or retry failed
builds. The script reuses existing reviewed notes and the fixed report layout.
If it fails (including missing results or review notes), return its error and stop.
Reviewing days is separate work, only when explicitly requested.

On success, return the generated file paths and the script's headline summary in
a short reply (roughly 100 words maximum). Relay any PDF skipped/failed message;
do not list a failed PDF as generated. Do not generate reports automatically after
/gradation.
