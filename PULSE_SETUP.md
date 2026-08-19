# Daily Client Pulse — Serverless Setup

The pulse now runs in GitHub Actions (`.github/workflows/pulse.yml` → `scripts/pulse.py`), daily at 6:05 AM Phoenix. Laptop can be off. Two secrets unlock it.

## 1. Vista Social API key (required)

The Vista API is a **paid add-on** — it must be enabled by Vista before a key works.

1. Message your Vista Social CSM / support: "Please provision our account for API access (API add-on)."
2. Once enabled: Vista Social → **Settings → Account Settings → Integrations** → generate API key.
3. GitHub → `kingsmedia1/pulse-data` → **Settings → Secrets and variables → Actions → New repository secret**
   - Name: `VISTA_API_KEY` — Value: the key.

## 2. Notion token (required for the Notion board; dashboard works without it)

1. https://www.notion.so/my-integrations → **New integration** (workspace: Kings Media, type: Internal). Copy the secret (`ntn_…`).
2. Open the **Daily Client Pulse** page in Notion → `⋯` menu → **Connections → Add connection** → pick the integration. (This grants access to the page AND the client table inside it.)
3. Add repo secret: Name `NOTION_TOKEN` — Value: the secret.

## 3. Test

Repo → **Actions → Daily Client Pulse → Run workflow**. Green check = done; the run log prints totals. Verify https://kingsmedia1.github.io/pulse-data/ and the Notion board updated.

## Notes

- Without `NOTION_TOKEN`, the run still refreshes the web dashboard (data.json) and skips Notion with a warning.
- Vista's API excludes X/Twitter data (their API terms). Twitter contributes <0.01% of your impressions, so numbers will match the old pipeline within rounding.
- Roster is auto-reconciled from Vista CLIENT groups: new clients get a Notion row, removed clients get archived.
- Change the run time in `pulse.yml` (`cron`, UTC).
- The old laptop-side scheduled task can be deleted once a manual Actions run is green.
- First run prints the raw Vista field names in the log — if Vista names metrics differently than expected, ping Claude with the log and it's a one-line fix.
