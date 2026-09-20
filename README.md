# AI News Digest

Project that generates a daily AI news digest from several RSS feeds
(fan-out), combined into a single summary (merge).

## Structure

- `feeds.yaml` — list of RSS sources to follow (edit it to add/remove sources).
- `fetch_digest.py` — script that reads all feeds, filters by date, deduplicates and
  saves the digest to `output/digest_YYYY-MM-DD.md`. It doesn't use any paid API: it
  only collects and filters headlines.
- `priorities.yaml` — relevance filter (labs/themes to prioritize, noise patterns to
  discard) used to keep only the top items per category.
- `requirements.txt` — dependencies (`feedparser`, `PyYAML`).
- `.github/workflows/digest.yml` — ready-to-use GitHub Actions workflow (free daily
  cron) that generates the digest and sends it to Telegram.

## How to run it locally or on GitHub Actions

```bash
pip install -r requirements.txt
python3 fetch_digest.py            # default window: last 26 hours
```

This works unchanged both on your own computer and on GitHub Actions, since both
have normal internet access.

## Automation

The digest runs automatically every day via the GitHub Actions workflow
(`.github/workflows/digest.yml`, cron at 8 AM Auckland time), which generates the
digest and sends it to Telegram using the `TELEGRAM_BOT_TOKEN` and
`TELEGRAM_CHAT_ID` repository secrets.

## Sources covered

See `feeds.yaml`. Note: Anthropic doesn't publish a public RSS feed at
anthropic.com/news as of today (checked: returns 404); if they add one in the
future, it can be added to the list.
