# ReciApp PostgreSQL Migrations

Apply the bootstrap schema to a fresh self-hosted PostgreSQL database:

```sh
psql "$DATABASE_URL" -f migrations/001_init.sql
```

`001_init.sql` is the first migration and should run before any future numbered migrations.
It consolidates the useful public schema from `supabase/migrations/*.sql`; that directory is legacy reference material and should not be applied to the self-hosted database.
