-- Link public.users to Supabase Auth so RevenueCat webhooks can find the row
-- by app_user_id. Email stays for existing lookups; it is no longer required,
-- because Apple/Google sign-in can omit it. Existing rows are not rewritten.
ALTER TABLE public.users
  ADD COLUMN IF NOT EXISTS auth_user_id uuid;

CREATE UNIQUE INDEX IF NOT EXISTS users_auth_user_id_key
  ON public.users (auth_user_id);

ALTER TABLE public.users
  ALTER COLUMN email DROP NOT NULL;

COMMENT ON COLUMN public.users.auth_user_id IS 'Supabase Auth user id. RevenueCat app_user_id after logIn.';
