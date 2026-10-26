-- Retry-until-dismissed (Pro add-on).
-- retry_minutes: gap in minutes before an unanswered ring rings again (up to 6 re-rings).
--   NULL = off (every existing alarm), so old rows behave exactly as before.
-- Apply BEFORE deploying the backend that writes this column, and before shipping the app build.

alter table public.alarms add column if not exists retry_minutes integer;

alter table public.alarms drop constraint if exists alarms_retry_minutes_range;
alter table public.alarms add constraint alarms_retry_minutes_range
  check (retry_minutes is null or retry_minutes between 5 and 60);

comment on column public.alarms.retry_minutes is
  'Retry-until-dismissed: minutes between re-rings when a ring is not dismissed; NULL = off';
