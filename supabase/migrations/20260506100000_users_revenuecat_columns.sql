-- RevenueCat webhook sync (https://api.ripplealarm.com/revenuecat)
-- Safe if columns already exist in Supabase.
ALTER TABLE public.users
  ADD COLUMN IF NOT EXISTS rc_customer_id text,
  ADD COLUMN IF NOT EXISTS rc_subscription_status text,
  ADD COLUMN IF NOT EXISTS rc_subscription_plan text;

COMMENT ON COLUMN public.users.rc_customer_id IS 'RevenueCat original_app_user_id / subscriber anchor.';
COMMENT ON COLUMN public.users.rc_subscription_status IS 'Webhook-derived: active, expired, inactive, billing_issue.';
COMMENT ON COLUMN public.users.rc_subscription_plan IS 'annual | monthly | trial | intro | unknown';
