# Operations

## Web Data Refresh

- Workflow: `.github/workflows/web-data-refresh.yml`
- Trigger in repository: manual `workflow_dispatch`
- Scheduled trigger: external `cron-job.org` jobs call the GitHub Actions workflow/API.
- Do not assume a missing `schedule:` block means refresh is unscheduled. The schedule is managed outside this repository.

## Scale Checks

The refresh workflow runs `scripts/report_operational_scale.py` after data refreshes. Check the Actions logs for lines beginning with `[scale]`.

Watch these values before public traffic spikes:

- `watchlists.unique_tickers`: total distinct tickers across all user watchlists. If this grows beyond `MAX_REFRESH_UNIVERSE`, refresh coverage and cache size need review.
- `cache.*.bytes`: static JSON payload size. Large JSON files increase first-load time and Vercel/CDN transfer.
- `watchlists.max_size`: should stay at or below the product limit of 50 per user.


## Deployment

- Vercel is connected to GitHub push auto-deploy.
- Pushing to the GitHub repository deploys the web app automatically through Vercel.
- The workflow's `Deploy refreshed web` step can remain skipped when `VERCEL_TOKEN` is empty, as long as the GitHub-to-Vercel integration is active.

## Email Notifications

Required GitHub Secrets:

- `SMTP_USER`
- `SMTP_PASSWORD`
- `SMTP_FROM`
- `SUPABASE_URL`
- `SUPABASE_SERVICE_ROLE_KEY`
- `WEB_APP_URL`

Optional GitHub Secrets:

- `SMTP_HOST` defaults to `smtp.gmail.com` when empty.
- `SMTP_PORT` defaults to `465` when empty.
- `SMTP_FROM_NAME` defaults to `공수성가`.
- `ADMIN_EMAILS` is used as the fallback admin recipient list.
- `EMAIL_PROVIDER` defaults to `smtp`. Set it to `brevo` to use Brevo.
- `BREVO_API_KEY` is required only when `EMAIL_PROVIDER=brevo`.
- `NOTIFICATION_UNSUBSCRIBE_SECRET` signs one-click unsubscribe links. When empty, `SUPABASE_SERVICE_ROLE_KEY` is used as the signing secret.
- `EMAIL_SEND_ATTEMPTS` defaults to `3`.

For Gmail, `SMTP_PASSWORD` must be an app password, not the normal account password.
Brevo is the preferred free-volume upgrade path when notification volume outgrows Gmail SMTP.

Notification failures are not ignored. If an email step fails, the GitHub Actions run should fail and appear in the repository Actions tab.

One-click unsubscribe links require these Vercel environment variables on the deployed web app:

- `SUPABASE_URL`
- `SUPABASE_SERVICE_ROLE_KEY`
- `WEB_APP_URL`
- `NOTIFICATION_UNSUBSCRIBE_SECRET` if it is set in GitHub Secrets

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
