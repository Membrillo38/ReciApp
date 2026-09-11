# ReciApp PostgreSQL Migrations

Apply the bootstrap schema to a fresh self-hosted PostgreSQL database:

```sh
psql "$DATABASE_URL" -f migrations/001_init.sql
```

`001_init.sql` is the first migration and should run before any future numbered migrations.
It is the schema for the self-hosted PostgreSQL database.
