-- User-managed alarm categories.
-- Existing global rows remain system defaults (`user_id IS NULL`).

ALTER TABLE public.category
    ADD COLUMN IF NOT EXISTS user_id bigint REFERENCES public.users (id) ON DELETE CASCADE,
    ADD COLUMN IF NOT EXISTS icon text NOT NULL DEFAULT '⭐',
    ADD COLUMN IF NOT EXISTS color_key text NOT NULL DEFAULT 'purple',
    ADD COLUMN IF NOT EXISTS sort_order integer NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS is_archived boolean NOT NULL DEFAULT false,
    ADD COLUMN IF NOT EXISTS created_at timestamptz NOT NULL DEFAULT now(),
    ADD COLUMN IF NOT EXISTS updated_at timestamptz NOT NULL DEFAULT now();

UPDATE public.category
SET icon = CASE lower(name)
    WHEN 'health' THEN '💊'
    WHEN 'plants' THEN '🌱'
    WHEN 'maintenance' THEN '🔧'
    WHEN 'pets' THEN '🐾'
    WHEN 'work' THEN '💼'
    WHEN 'custom' THEN '⭐'
    ELSE icon
END,
color_key = CASE lower(name)
    WHEN 'plants' THEN 'green'
    WHEN 'maintenance' THEN 'amber'
    WHEN 'pets' THEN 'amber'
    ELSE 'purple'
END,
sort_order = CASE lower(name)
    WHEN 'health' THEN 10
    WHEN 'plants' THEN 20
    WHEN 'maintenance' THEN 30
    WHEN 'pets' THEN 40
    WHEN 'work' THEN 50
    WHEN 'custom' THEN 60
    ELSE sort_order
END
WHERE user_id IS NULL;

CREATE UNIQUE INDEX IF NOT EXISTS category_system_name_unique_idx
    ON public.category (lower(name))
    WHERE user_id IS NULL AND is_archived = false;

CREATE UNIQUE INDEX IF NOT EXISTS category_user_name_unique_idx
    ON public.category (user_id, lower(name))
    WHERE user_id IS NOT NULL AND is_archived = false;

CREATE INDEX IF NOT EXISTS category_user_active_idx
    ON public.category (user_id, is_archived, sort_order, name);
