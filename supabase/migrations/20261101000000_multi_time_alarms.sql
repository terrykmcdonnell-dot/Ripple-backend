-- v2 Multi-Time Alarms.
-- ring_times: JSON array of local wall-clock "HH:mm" strings (sorted, max 6, first entry
--   matches scheduled_at's local time). NULL = legacy single-time alarm; existing rows are
--   left untouched and the app derives their single time from scheduled_at.
-- skipped_fires: JSON array of ISO occurrence instants the user chose to skip.
-- Apply BEFORE deploying the backend that writes these columns, and before shipping app 1.0.17.

alter table public.alarms add column if not exists ring_times jsonb;
alter table public.alarms add column if not exists skipped_fires jsonb;

comment on column public.alarms.ring_times is
  'v2 multi-time: JSON array of local wall-clock "HH:mm" ring times; NULL = single-time (derived from scheduled_at)';
comment on column public.alarms.skipped_fires is
  'v2 multi-time: JSON array of ISO occurrence instants skipped by the user';
