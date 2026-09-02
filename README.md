# Recipe Extractor API

Backend barato para iOS: pega URL de TikTok / YouTube / Instagram / Facebook y devuelve receta estructurada.

## Coste Render

| Plan | Precio | Siempre ON |
|------|--------|------------|
| Free | $0 | No (duerme a los 15 min) |
| **Starter** | **$7/mes** | **Sí** |

Este proyecto usa **Starter** en `render.yaml`. Es el mínimo para 24/7.

Coste API OpenAI (aprox):
- YouTube con subtítulos: ~$0.001/receta
- TikTok con gpt-4o-mini-transcribe 60s: ~$0.003/receta
- Slideshow OCR: ~$0.01–0.03/receta

## Stack

- FastAPI + uvicorn
- yt-dlp + ffmpeg (Docker)
- OpenAI gpt-4o-mini-transcribe (audio)
- OpenAI GPT-4o-mini (receta JSON)
- Jobs async en memoria (sin Redis, 1 instancia)

## Deploy en Render

1. Sube repo a GitHub (solo carpeta `recipe-extractor-api`).
2. Render Dashboard → **New** → **Blueprint** → conecta repo.
3. Render lee `render.yaml` y crea servicio Docker plan **starter**.
4. Añade env var manual:
   - `OPENAI_API_KEY` = tu key OpenAI
5. `API_KEY` se genera sola. Cópiala para la app iOS.
6. URL final: `https://recipe-extractor.onrender.com`

### Deploy manual (sin Blueprint)

1. New Web Service → Docker
2. Plan: **Starter**
3. Region: **Frankfurt** (EU)
4. Health check: `/health`
5. Env vars: `OPENAI_API_KEY`, `API_KEY`

## API

### Health
```http
GET /health
```

### Crear extracción
```http
POST /v1/extract
Content-Type: application/json
X-API-Key: tu-api-key

{ "url": "https://www.tiktok.com/@user/video/123" }
```

Respuesta:
```json
{ "job_id": "uuid", "status": "pending" }
```

### Consultar job (polling cada 2–3s)
```http
GET /v1/jobs/{job_id}
X-API-Key: tu-api-key
```

Cuando `status` = `completed`, campo `recipe` tiene la receta.

## Flujo interno

```
URL
 → detect platform
 → TikTok slideshow? → OCR slides → GPT → recipe
 → else yt-dlp metadata
 → subtitles / YouTube transcript / gpt-4o-mini-transcribe
 → GPT structured JSON → recipe
```

## Local

```bash
cd recipe-extractor-api
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
# ffmpeg required: brew install ffmpeg

export OPENAI_API_KEY=sk-...
export API_KEY=dev-key

uvicorn app.main:app --reload --port 8000
```

## iOS (header)

Todas las requests llevan:
```
X-API-Key: <API_KEY de Render>
```

Polling:
1. POST `/v1/extract`
2. Loop GET `/v1/jobs/{id}` hasta `completed` o `failed`

## Límites

- Vídeos > 10 min rechazados (`MAX_DURATION_SECONDS`)
- Instagram/Facebook: depende de yt-dlp (puede fallar)
- 1 instancia: jobs en RAM, se pierden si Render reinicia el contenedor

## Archivos

- `app/main.py` — endpoints
- `app/pipeline.py` — orquestación + jobs
- `app/extract.py` — yt-dlp
- `app/transcript.py` — gpt-4o-mini-transcribe / YouTube / OCR
- `app/recipe_builder.py` — GPT JSON
- `Dockerfile` — Python + ffmpeg
- `render.yaml` — Blueprint Starter always-on
