-- Expand recipe_translations language allowlist to 50 App Store locales.
alter table public.recipe_translations
  drop constraint if exists recipe_translations_language_code_check;

alter table public.recipe_translations
  add constraint recipe_translations_language_code_check
  check (language_code in (
    'ar', 'bn', 'ca', 'zh-Hans', 'zh-Hant', 'hr', 'cs', 'da', 'nl',
    'en-AU', 'en-CA', 'en-GB', 'en-US', 'fi', 'fr-FR', 'fr-CA', 'de', 'el',
    'gu', 'he', 'hi', 'hu', 'id', 'it', 'ja', 'kn', 'ko', 'ms', 'ml', 'mr',
    'nb', 'or', 'pl', 'pt-BR', 'pt-PT', 'pa', 'ro', 'ru', 'sk', 'sl',
    'es-MX', 'es-ES', 'sv', 'ta', 'te', 'th', 'tr', 'uk', 'ur', 'vi'
  ));
