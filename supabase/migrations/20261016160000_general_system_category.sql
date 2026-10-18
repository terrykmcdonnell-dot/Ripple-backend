-- Neutral default category. Does not rename or rewrite existing categories or alarms.
insert into public.category (name, icon, color_key, sort_order, user_id, is_archived)
select 'General', '🔔', 'blue', 5, null, false
where not exists (
  select 1
  from public.category c
  where c.user_id is null
    and lower(c.name) = 'general'
    and c.is_archived = false
);
