# Operations

## Web Data Refresh

- Workflow: `.github/workflows/web-data-refresh.yml`
- Trigger in repository: manual `workflow_dispatch`
- Scheduled trigger: external `cron-job.org` jobs call the GitHub Actions workflow/API.
- Do not assume a missing `schedule:` block means refresh is unscheduled. The schedule is managed outside this repository.

## Email Notifications

Required GitHub Secrets:

- `SMTP_USER`
- `SMTP_PASSWORD`
- `SMTP_FROM`
- `SUPABASE_URL`
- `SUPABASE_SERVICE_ROLE_KEY`

Optional GitHub Secrets:

- `SMTP_HOST` defaults to `smtp.gmail.com` when empty.
- `SMTP_PORT` defaults to `465` when empty.
- `SMTP_FROM_NAME` defaults to `공수성가`.
- `ADMIN_EMAILS` is used as the fallback admin recipient list.

For Gmail, `SMTP_PASSWORD` must be an app password, not the normal account password.

Notification failures are not ignored. If an email step fails, the GitHub Actions run should fail and appear in the repository Actions tab.

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
