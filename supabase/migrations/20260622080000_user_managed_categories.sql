-- User-managed categories.
--
-- Existing `alarms.category` rows point at `category.id`; keep that table and
-- extend it with ownership + display metadata. `user_id is null` means a
-- system/default category visible to every user.

alter table public.category
  add column if not exists user_id integer references public.users(id) on delete cascade,
  add column if not exists icon text not null default '⭐',
  add column if not exists color_key text not null default 'purple',
  add column if not exists sort_order integer not null default 100,
  add column if not exists is_archived boolean not null default false,
  add column if not exists created_at timestamptz not null default now(),
  add column if not exists updated_at timestamptz not null default now();

update public.category
set
  icon = case lower(name)
    when 'health' then '💊'
    when 'plants' then '🌱'
    when 'maintenance' then '🔧'
    when 'pets' then '🐾'
    when 'work' then '💼'
    when 'custom' then '⭐'
    else icon
  end,
  color_key = case lower(name)
    when 'plants' then 'green'
    when 'maintenance' then 'amber'
    when 'pets' then 'amber'
    else 'purple'
  end,
  sort_order = case lower(name)
    when 'health' then 10
    when 'plants' then 20
    when 'maintenance' then 30
    when 'pets' then 40
    when 'work' then 50
    when 'custom' then 60
    else sort_order
  end
where lower(name) in ('health', 'plants', 'maintenance', 'pets', 'work', 'custom');

insert into public.category (name, icon, color_key, sort_order, user_id, is_archived)
select seed.name, seed.icon, seed.color_key, seed.sort_order, null, false
from (
  values
    ('Health', '💊', 'purple', 10),
    ('Plants', '🌱', 'green', 20),
    ('Maintenance', '🔧', 'amber', 30),
    ('Pets', '🐾', 'amber', 40),
    ('Work', '💼', 'purple', 50),
    ('Custom', '⭐', 'purple', 60)
) as seed(name, icon, color_key, sort_order)
where not exists (
  select 1
  from public.category c
  where c.user_id is null and lower(c.name) = lower(seed.name)
);

create unique index if not exists category_system_name_unique
  on public.category (lower(name))
  where user_id is null and is_archived = false;

create unique index if not exists category_user_name_unique
  on public.category (user_id, lower(name))
  where user_id is not null and is_archived = false;

create index if not exists category_user_visible_idx
  on public.category (user_id, is_archived, sort_order);
