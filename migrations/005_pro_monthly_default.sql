-- Raise default Pro monthly revenue baseline to monthlyized ~$9.99/week
-- (mid of weekly A/B band $6.99–$12.99). Fair-use = this × (1 - margin).

update public.app_settings
   set default_pro_monthly_price_cents = 4329
 where id = 1
   and default_pro_monthly_price_cents = 499;
