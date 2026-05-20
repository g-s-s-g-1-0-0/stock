alter table user_settings
  alter column notification_preferences set default '{"opinionChangeEmail":true,"nasdaqPeakEmail":true,"bbPullbackEmail":true,"weeklyTrendReport":true,"earningsDayBefore":true,"adminAutoUpdateFailureEmail":true,"recipientEmail":"","notificationChannel":"email","kakaoTalkConnected":false,"slackConnected":false,"kakaoTalkConnectedAt":"","slackConnectedAt":""}'::jsonb;

update user_settings
set notification_preferences = jsonb_set(
  coalesce(notification_preferences, '{}'::jsonb),
  '{bbPullbackEmail}',
  'true'::jsonb,
  true
)
where not coalesce(notification_preferences, '{}'::jsonb) ? 'bbPullbackEmail';
