# Idea: LINE bot that runs /gradation automatically

Status: **parked idea (2026-10-04), not approved or built.** Discuss before implementing.

## Why

Today the workflow is:
1. A blaster sends a photo in LINE.
2. It is saved and renamed to `MMDDYYYY.jpg`.
3. It is moved into `stockpile_picture/<YYYY-MM>/`.
4. `/gradation` is run.

The goal is to make this hands-off.

Decisions so far:
- **A fully automatic LINE bot.** The alternatives that were considered:
  - an inbox folder with an auto-run;
  - a script only with a fixed ROI and no AI;
  - a rename/move helper only.
- **File date = the date the photo was received in LINE**, in Asia/Bangkok time.

Claude still runs the analysis, so each photo still gets its own ROI and overlay check (water, cliff, missing pole). Results go back to LINE.

## Architecture

```
LINE group (blaster posts photo)
  → LINE Messaging API webhook (HTTPS)
  → ngrok static domain (ngrok.exe already installed)
  → line_bot.py on this PC (Python stdlib http server, no new packages)
      1. verify X-Line-Signature (HMAC-SHA256 with channel secret)
      2. accept only image messages from the allowed group ID
      3. download https://api-data.line.me/v2/bot/message/{id}/content
      4. name = event timestamp → Asia/Bangkok date → MMDDYYYY
         save to stockpile_picture/<YYYY-MM>/<MMDDYYYY>.jpg
      5. queue a job (one at a time); reply 200 to LINE immediately
      6. worker: claude -p "/gradation stockpile_picture/<YYYY-MM>/<MMDDYYYY>.jpg"
      7. push to the group: Claude's summary table + overlay image
```

## Files it would add or change

- **`line_bot.py`** (new, standard library only):
  - contains the webhook, signature check, download, naming, job queue with one worker, the headless Claude call and the push message;
  - serves `GET /overlay/<token>.png` so LINE can fetch the overlay. The token is random and the path is read-only.
- **`.env`** (gitignored) holds:
  - `LINE_CHANNEL_SECRET`
  - `LINE_CHANNEL_ACCESS_TOKEN`
  - `LINE_GROUP_ID`
  - `PUBLIC_BASE_URL`
- **`.gitignore`**: add `.env` and `bot_logs/`.
- **`.claude/settings.json`**: an allowlist so headless `/gradation` runs without prompts:
  - `Read`;
  - `PowerShell` limited to `.\.venv\Scripts\python.exe -B rock_gradation.py …` and the template's `New-Item`/`Get-Content` lines.
- **`start_bot.ps1`**:
  - starts `ngrok http --domain=<static> 8080` and `line_bot.py`;
  - runs from Task Scheduler at logon, restarting on failure.
- **`CLAUDE.md`**: a short section on the bot.

## Behaviour rules

- **Date:** from the LINE event timestamp, converted to Asia/Bangkok. This is wrong if a photo is sent a day late, and the confirmation message shows the date so it can be caught.
- **Second photo on the same day:**
  - save it as `MMDDYYYY_2.jpg` with output in `output/<YYYY-MM>/<YYYY-MM-DD>-2/`;
  - never overwrite;
  - flag it as not the official day result.
- **Headless /gradation** cannot ask questions:
  - if there is no pole or a blocking defect, it ends with `failed:`/`needs input:`, and the bot forwards that text;
  - a timeout of about 15 minutes;
  - logs go to `bot_logs/<stem>.log`.
- **Push message:**
  - Claude's final reply, trimmed to 5,000 characters;
  - the overlay PNG via `PUBLIC_BASE_URL`, original under 10 MB, preview under 1 MB.
- **Security:** reject bad signatures, unknown groups and non-image messages. No shell string building.

## Prerequisites (user actions)

1. Create a LINE Official Account and Messaging API channel at developers.line.biz. Then:
   - allow the bot to join group chats;
   - disable auto-reply;
   - copy the secret and the access token.
2. Claim the free ngrok static domain and set the webhook URL to `https://<domain>/callback`.
3. Invite the bot into the blaster group. The bot logs the group ID on the first event; put it in `.env`.
4. **Kaspersky** blocks scripts from writing `*.jpg`, so the bot's download would fail. Either:
   - add an exclusion for the repo folder, or
   - have the bot save the photo as `.png`.
5. The PC must stay on and logged in.

## Limits and cost

- **Messages:** the free LINE plan allows about 300 push messages a month (Thailand). One photo a day with text and image is about 60 a month.
- **Reply tokens:** these expire too fast for a multi-minute analysis, so the bot uses push messages.
- **Claude usage:** each photo uses one `/gradation` run.

## Verification (when built)

1. Unit tests for:
   - the signature check;
   - timestamp → Bangkok date → `MMDDYYYY`, including just after midnight;
   - same-day `_2` naming.
2. Local test: post a signed sample webhook with a mocked download → the file lands in the right month folder and the job is queued.
3. Live test: send a known photo into the group → the table and overlay come back.
4. Full suite: `.\.venv\Scripts\python.exe -B -m unittest discover -s tests -v`.
