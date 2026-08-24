# Operations

## Web Data Refresh

- Workflow: `.github/workflows/web-data-refresh.yml`
- Trigger in repository: manual `workflow_dispatch`
- Two-hour analysis refresh: external `cron-job.org` jobs call `/api/admin/trigger-refresh`, which dispatches the workflow. Those jobs live outside this repository, so a short `schedule:` block does not mean the refresh is unscheduled.
- Keep GitHub's native `schedule:` block minimal to avoid duplicate refreshes with the external scheduler. It holds only `0 15 * * *` (daily valuation + earnings D-1) and `0 15 * * 0` (weekly market trends + universe report).
- GitHub queues scheduled runs at low priority and regularly delays them by tens of minutes to a few hours. Do not put time-sensitive notifications on `schedule:`. A delayed run that refreshes analysis caches also republishes them off the two-hour cadence, so `meta.updatedAt` will not always land on the hour.

## Scale Checks

The refresh workflow runs `scripts/report_operational_scale.py` after data refreshes. Check the Actions logs for lines beginning with `[scale]`.

Watch these values before public traffic spikes:

- `watchlists.unique_tickers`: total distinct tickers across all user watchlists. If this grows beyond `MAX_REFRESH_UNIVERSE`, refresh coverage and cache size need review.
- `cache.*.bytes`: static JSON payload size. Large JSON files increase first-load time and Vercel/CDN transfer.
- `watchlists.max_size`: should stay at or below the product limit of 50 per user.


## Deployment

- Vercel is connected to GitHub push auto-deploy for real app/code changes.
- Scheduled cache refreshes commit `web/public/api/*.json` only. `web/vercel.json` ignores those data-only builds so Vite is not rebuilt every two hours (a rebuild without `VITE_SUPABASE_*` previously took login offline).
- After a data-only skip, the already-deployed app loads market JSON from GitHub (`raw.githubusercontent.com/.../web/public/api/`), with same-origin `/api/*.json` as fallback.
- Full app builds refuse to proceed when `VITE_SUPABASE_URL` / `VITE_SUPABASE_ANON_KEY` are missing (`web/scripts/assert-vite-supabase-env.mjs`).
- The refresh workflow smoke-checks production for an inlined `supabase.co` host after each cache publish and emails admins on failure.
- Admin market-event edits are saved by `web/api/admin/market-events.js`, which commits both `web/public/api/market-events.json` and `data/cache/market-events.json` through the GitHub API. Set `GITHUB_ACTIONS_TOKEN` with Actions and contents write access, `GITHUB_REPO`, and `GITHUB_REFRESH_REF` in Vercel.

## Email Notifications

Required GitHub Secrets:

- `SMTP_USER`
- `SMTP_PASSWORD`
- `SMTP_FROM`
- `SUPABASE_URL`
- `SUPABASE_SERVICE_ROLE_KEY`
- `WEB_APP_URL`

Required Vercel environment variables for admin refresh/save APIs:

- `GITHUB_ACTIONS_TOKEN`
- `GITHUB_REPO`
- `GITHUB_REFRESH_REF`
- `SUPABASE_URL`
- `SUPABASE_ANON_KEY`
- `ADMIN_EMAILS`

Required Vercel environment variables for Slack notifications:

- `SUPABASE_URL`
- `SUPABASE_ANON_KEY`
- `SUPABASE_SERVICE_ROLE_KEY`
- `WEB_APP_URL`
- `SLACK_CLIENT_ID`
- `SLACK_CLIENT_SECRET`
- `SLACK_SIGNING_SECRET`

In the Slack app's **OAuth & Permissions** settings, add `${WEB_APP_URL}/api/slack/oauth/callback` as a Redirect URL. Set all variables in the Vercel Production environment, then redeploy.

Optional GitHub Secrets:

- `SMTP_HOST` defaults to `smtp.gmail.com` when empty.
- `SMTP_PORT` defaults to `465` when empty.
- `SMTP_FROM_NAME` defaults to `공수성가`.
- `ADMIN_EMAILS` is used as the fallback admin recipient list.
- `EMAIL_PROVIDER` defaults to `smtp`. Set it to `brevo` to use Brevo.
- `BREVO_API_KEY` is required only when `EMAIL_PROVIDER=brevo`.
- `NOTIFICATION_UNSUBSCRIBE_SECRET` signs one-click unsubscribe links. When empty, `SUPABASE_SERVICE_ROLE_KEY` is used as the signing secret.
- `EMAIL_SEND_ATTEMPTS` defaults to `3`.
- `GROQ_MARKET_TREND_MODEL` defaults to `openai/gpt-oss-120b`. Set this if the Groq project restricts model access. Do not use the retired `llama-3.3-70b-versatile` model.

For Gmail, `SMTP_PASSWORD` must be an app password, not the normal account password.
Brevo is the preferred free-volume upgrade path when notification volume outgrows Gmail SMTP.

Notification failures are not ignored. If an email step fails, the GitHub Actions run should fail and appear in the repository Actions tab.

Weekly trend and earnings D-1 emails record what they sent in `data/cache/web-notification-state.json`, which the workflow commits after the email steps. A second trigger for the same report date (weekly) or the same KST date and ticker set (earnings) is skipped, so overlapping external cron and GitHub `schedule:` runs no longer resend the same mail. Look for `already_sent=` in the Actions log to confirm a skip.

One-click unsubscribe links require these Vercel environment variables on the deployed web app:

- `SUPABASE_URL`
- `SUPABASE_SERVICE_ROLE_KEY`
- `WEB_APP_URL`
- `NOTIFICATION_UNSUBSCRIBE_SECRET` if it is set in GitHub Secrets

## Removed Features

### Moving-average support notification (removed 2026-07-29)

Admin-only email that scanned watchlist tickers for 20/200-day moving-average support or breakout and was meant to send at 08:00 and 09:30 KST on weekdays.

Why it was removed: no recipient had `maSupportEmail` enabled, so the feature sent nothing while its two GitHub `schedule:` crons kept force-refreshing the technical cache. GitHub delivered those runs hours late (12:46–13:12 KST on 7/27–7/29 for the 09:30 slot), and because they ran with `FORCE_REFRESH=true` they bypassed the 90-minute freshness skip and republished `technical.json` off the two-hour cadence for no benefit.

What was removed:

- `.github/workflows/web-data-refresh.yml`: crons `0,10,20,30,40,50 23 * * 0-4` and `30,40,50 0 * * 1-5`, the `ma_support_scan_slot` input, the `MA_SUPPORT_SCAN_FORCE` / `MA_SUPPORT_SCAN_SLOT` env vars, and the `Send moving average support candidate emails` step
- `scripts/web_refresh_notifications.py`: the `ma-support` subcommand and every `ma_support_*` / `ma_signal_for_period` / `moving_average` helper, plus `technical_market_state`, `latest_ohlcv_date`, `format_ohlcv_date`, `resolve_market_from_ticker`, and the `fetch_ohlcv` import that only this feature used
- `web/api/admin/trigger-refresh.js`: slot parsing (`normalizeMaSupportSlot`, `readMaSupportScanSlot`, `seoulDateParts`, `isSeoulWeekday`) and the slot pass-through to the workflow
- `web/src/App.tsx` plus the notification defaults in `web/api/notifications/unsubscribe.js`, `web/api/slack/integration.js`, and `web/api/slack/oauth/callback.js`: the `maSupportEmail` preference
- `tests/test_web_refresh_notifications.py`: 9 `test_ma_support_*` tests, replaced by `assertNotIn` guards in the workflow structure test

Left in place on purpose:

- `supabase/migrations/016_ma_support_notification_preference.sql` remains as applied history, so `maSupportEmail` still sits in the `notification_preferences` default and in existing rows. This matches how `regimeShiftEmail` and `bbPullbackEmail` were retired — the key is simply ignored because the web client no longer reads it.
- `maSupportSignals` in `data/cache/web-notification-state.json` keeps the old dedup keys, so a restored feature would not resend past signals.

Also removed outside this repository: the `GSSG MA Support Refresh` and `GSSG MA Support Refresh (9:30 AM)` jobs in cron-job.org, deleted 2026-07-29. They had already been inactive since 2026-07-16, which is why the feature ran on GitHub `schedule:` crons and arrived hours late.

### Restoring it

Step 1 — restore the code. The last commit that still contains the feature is `188bd99`:

```bash
git checkout 188bd99 -- \
  .github/workflows/web-data-refresh.yml \
  scripts/web_refresh_notifications.py \
  web/api/admin/trigger-refresh.js \
  web/src/App.tsx \
  web/api/notifications/unsubscribe.js \
  web/api/slack/integration.js \
  web/api/slack/oauth/callback.js \
  tests/test_web_refresh_notifications.py
```

That restores the listed files wholesale, so review the diff for unrelated work that landed after the removal. Once other changes have touched those files, reverting the removal commit is the safer path.

Step 2 — recreate the cron-job.org jobs. Code alone brings back the GitHub `schedule:` crons, which do fire but arrive tens of minutes to hours late, so morning emails would again be labelled `1차 08:00` / `2차 09:30` while landing near noon. Punctual delivery needs the external scheduler, which fires on time. Create two jobs calling `/api/admin/trigger-refresh` a few minutes before each slot, on weekdays, passing `secret=$CRON_SECRET`, `scope=technical`, and `ma_support_scan_slot=08` or `0930`. Mirror the existing `GSSG Technical Refresh` job for the URL shape and secret.

Note that Step 1 also restores the slot handling in `trigger-refresh.js`, where a request carrying a slot is forced to `scope=technical` and publishes immediately instead of waiting for the top of the hour. Until Step 1 is done, a job that sends only a slot and no `scope` falls back to `scope=all` and runs a full refresh.

Step 3 — enable a recipient. The email only goes to admins who have `maSupportEmail` turned on. Nobody had it enabled at removal time, so verify the toggle in notification settings before expecting mail.

## GitHub Push Permission

Pushing changes to `.github/workflows/*` requires a GitHub token with the `workflow` scope.

Check current scopes:

```bash
gh auth status
```

Refresh scopes for the active account:

```bash
gh auth refresh -h github.com -s workflow
```

If multiple GitHub accounts are logged in, switch to the account that has `repo` and `workflow` scopes:

```bash
gh auth switch -h github.com -u <github-username>
```

Then push again:

```bash
git push
```
