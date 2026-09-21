# Checklist iOS ↔ server (VPS)

Server en Coolify `main`. Margen Pro **40%**, reserva job **50¢**, OCR último recurso.  
API: `https://51-255-43-100.sslip.io`  
Free: **3 miss / año**. Pro fair-use: budget = precio×0.60.

Usa esto como lista de huecos en la app. Lo ya OK se marca.

---

## Ya alineado (server + iOS base)

- [x] `AppConfig.apiBaseURL` → VPS `51-255-43-100.sslip.io` (no Render).
- [x] Superwall `identify` + attribute **`user_id`** (UUID backend). Server acepta también legacy `supabase_user_id`.
- [x] Paywall en `FREE_WEEKLY_LIMIT` / `FREE_YEARLY_LIMIT` (= 3/año en prod).
- [x] UI fair-use en `PRO_FAIR_USE_LIMIT`.
- [x] `warmUpBackend()` antes de auth.
- [x] Poll job / refresh `/v1/me` tras compra.
- [x] Prod `/health` + `/ready` OK (`environment=production`).
- [x] Webhook Superwall VPS: `https://51-255-43-100.sslip.io/v1/webhooks/superwall`.
- [x] Server códigos job canónicos (`link_in_bio`, `extraction_retryable`, carousel, etc.).
- [x] Server emite `SPEND_LIMIT` (403) cuando budget OpenAI se agota.

---

## Revisar / completar en iOS

### 1. `SPEND_LIMIT` (403) — pendiente cliente

Server puede devolver:

```json
{"detail":{"code":"SPEND_LIMIT","message":"Usage budget reached.","reason":"…"}}
```

Hoy cae en `showForbidden` genérico (`ClientStatePolicy`).

**Hacer:**
- Tratar `SPEND_LIMIT` como **límite temporal del server**, no paywall.
- Copy tipo: “Demasiado uso ahora. Prueba en unos minutos.”
- No abrir Superwall.
- No borrar la cola de import; permitir retry después.

Archivo: `ReciApp/Services/ClientStatePolicy.swift` (+ mensaje en `Models.swift` / strings).

### 2. Copy cuota Free

Server real: **3 miss / año** (`FREE_WEEKLY_LIMIT` = nombre legacy).

**Hacer:** unificar copy UI + docs a **3 / año**.

### 3. Errores de job (extract) — pendiente cliente

Server guarda mensajes canónicos en inglés (localiza en API cuando aplica):

| Mensaje / sentido | Código interno server |
|---|---|
| Recipe link in bio… | `link_in_bio` |
| Incomplete TikTok carousel… | `incomplete_carousel` |
| Missing ingredient list / steps | `recipe_no_ingredients` / `recipe_no_method` |
| Extraction temporarily failed. Retry… | `extraction_retryable` |
| Video too long… | `video_too_long` |
| Unsupported URL… | `unsupported_url` |

**Hacer:**
- Mostrar `job.error` al usuario (no tragarlo en genérico).
- `extraction_retryable` / “Retry the import” → CTA **Reintentar**, no culpar al enlace.
- `link_in_bio` → copy claro: la receta está en el bio del creador; no es fallo de la app.
- Si más adelante el job expone `error_code`, preferir código; hoy suele ser el string.

### 4. QA post-cambio server

1. **Caption completa** (TikTok/IG) → OK sin tardar mucho (sin OCR).
2. **“Recipe in bio”** → error bio, **sin** gasto raro / sin spinner eterno.
3. **Carrusel** con caption incompleta → puede OCR slides; si falla mid-way, mensaje carousel incompleto.
4. **Video sin caption** → local STT primero; si local habla bastante, no debería ir a OpenAI STT.
5. **Mismo enlace otra vez** → cache hit, no cuenta cuota Free.
6. Free: 3 miss nuevos en el año → paywall. El 4.º falla con `FREE_WEEKLY_LIMIT`.
7. Pro: tras mucho uso OpenAI del mes (budget = precio×0.60) → `PRO_FAIR_USE_LIMIT`, no paywall de compra.

### 5. Superwall dashboard

- Webhook solo VPS (ya).
- No apuntar a ningún `*.onrender.com`.
- Attribute en eventos: `user_id`.

### 6. Docs iOS a sync

- [ ] Strings Localizable: mensajes bio / retry / spend limit.
- [ ] Copy Free = **3 / año** en UI.

### 7. Opcional (no bloquea)

- Renombrar comentarios “weekly limit” → “yearly free cap” en UI/código.
- Analytics: event cuando `SPEND_LIMIT`.

---

## Qué no tocar en iOS

- No hace falta cambiar URL de API (ya VPS).
- No hace falta `supabase_user_id` (ya usáis `user_id`).
- No hace falta lógica OCR/STT en cliente: eso es solo server.

---

## Smoke mínimo prod

1. Sign in with Apple.
2. Import 1 TikTok/IG video con caption rica.
3. Import 1 “recipe in bio” → mensaje correcto.
4. Re-import mismo link → instant / cache.
5. Settings → Upgrade / restore → `/v1/me` `is_pro`.
6. Free: quemar cuota (3) y ver paywall `free_limit_reached`.

Si algo de la lista 1–3 no está, prioriza **`SPEND_LIMIT`** y **mostrar `job.error`**.
