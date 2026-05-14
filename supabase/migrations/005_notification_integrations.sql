create table if not exists public.notification_integrations (
  owner_id uuid not null references auth.users(id) on delete cascade,
  provider text not null check (provider in ('slack')),
  team_id text,
  team_name text,
  channel_id text,
  channel_name text,
  webhook_url text not null,
  configuration_url text,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  primary key (owner_id, provider)
);

alter table public.user_settings
  alter column notification_preferences set default '{"opinionChangeEmail":true,"nasdaqPeakEmail":true,"weeklyTrendReport":true,"earningsDayBefore":true,"adminAutoUpdateFailureEmail":true,"recipientEmail":"","notificationChannel":"email","kakaoTalkConnected":false,"slackConnected":false,"kakaoTalkConnectedAt":"","slackConnectedAt":""}'::jsonb;

drop trigger if exists notification_integrations_touch_updated_at on public.notification_integrations;
create trigger notification_integrations_touch_updated_at
  before update on public.notification_integrations
  for each row execute function public.touch_updated_at();

alter table public.notification_integrations enable row level security;

drop policy if exists "notification_integrations_admin_read" on public.notification_integrations;
create policy "notification_integrations_admin_read"
  on public.notification_integrations
  for select
  using (public.current_user_is_admin());
