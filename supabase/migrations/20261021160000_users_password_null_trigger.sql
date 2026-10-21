-- Defense in depth: old app builds still send a value for users.password on sign-in,
-- sign-up, and password reset (new builds already send an empty string). This trigger
-- discards whatever is sent on every insert and update, so nothing is ever persisted
-- here again. The real password lives only in Supabase Auth (hashed, not in this table).
-- Safe to run more than once.

-- Make the column nullable first — if it was created NOT NULL, the trigger's NULL
-- write would otherwise fail every insert/update on this table. A no-op if it is
-- already nullable.
ALTER TABLE public.users
  ALTER COLUMN password DROP NOT NULL;

CREATE OR REPLACE FUNCTION public.users_null_password()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
  NEW.password := NULL;
  RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS users_null_password_trigger ON public.users;

CREATE TRIGGER users_null_password_trigger
  BEFORE INSERT OR UPDATE ON public.users
  FOR EACH ROW
  EXECUTE FUNCTION public.users_null_password();

COMMENT ON FUNCTION public.users_null_password() IS
  'Forces public.users.password to NULL on every write. Old app builds still send a value here; this trigger discards it before it reaches disk. The real password is stored hashed, only in Supabase Auth.';
