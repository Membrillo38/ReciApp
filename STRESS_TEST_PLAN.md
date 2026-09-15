# Plan científico de stress test del backend de recetas

**Estado:** plan preparado; no se ha implementado ni ejecutado ninguna prueba.

**Objetivo:** determinar cuántas recetas por segundo puede crear realmente la infraestructura, durante cuánto tiempo puede mantener ese ritmo, cuándo comienza la degradación, cuál es el primer cuello de botella, por qué falla y cuánto tarda en recuperarse.

**Coste objetivo:** 0 €. Las pruebas se ejecutarán desde el Mac contra una infraestructura aislada de stress en el VPS, sin proveedores externos ni servicios de load testing de pago.

## 1. Límites y reglas de seguridad

No se implementará ni ejecutará nada hasta la aprobación explícita de este plan.

Durante el trabajo:

- No se utilizará la base de datos de producción.
- No se desplegará en producción ni se hará push a un entorno auto-desplegable.
- No se llamará a OpenAI, scraping, TTS, analytics, webhooks, email, Telegram, Backblaze B2 ni ningún otro proveedor externo.
- No se usarán servicios cloud de load testing.
- La destrucción de la base de datos, volumen o stack de stress será una acción separada, protegida y con confirmación explícita.
- Si se pierde el acceso SSH, se reinicia un contenedor, aparece OOM, se detecta corrupción o se amenaza la disponibilidad del VPS, se detendrá la carga y se conservarán los artefactos.

La capacidad calculada será la capacidad observada de la configuración y hardware probados, no una garantía universal para otras regiones, versiones, tamaños de instancia o configuraciones.

## 2. Auditoría realizada antes de este plan

La auditoría fue únicamente de código, configuración, Docker, migraciones y documentación local. No se consultó ni modificó el VPS, no se tocó PostgreSQL y no se lanzó carga.

### Componentes relevantes

- API FastAPI en `app/main.py`, servida por un único proceso `uvicorn` sin `--workers` en el Dockerfile.
- Pipeline síncrono ejecutado desde tareas de background en `app/pipeline.py`.
- Pool global `psycopg_pool.ConnectionPool` con `min_size=1` y `max_size=10` en `app/db.py`.
- Límite interno de slots de extracción configurable, actualmente `MAX_CONCURRENT_JOBS=8` por defecto.
- Worker durable opcional; `WORKER_ENABLED=false` por defecto.
- Límite de cuerpo HTTP de 256 KiB y rate limits por IP, usuario, endpoint y día.
- Modo dry-run existente, pero el flujo actual de extracción dry-run usa media/ffmpeg/Whisper local y no aplica todos los parámetros declarados (`EXTRACT_DRY_RUN_MODE` y `EXTRACT_DRY_RUN_HOLD_MS`) tal como están documentados.
- La ruta de polling de jobs es un `GET` con posibles efectos de escritura al crear traducciones o adjuntar recetas.
- El middleware registra requests en `api_request_logs`, por lo que esa escritura debe medirse y aislarse durante el benchmark.

### Llamadas externas identificadas

- `yt-dlp`, oEmbed, subtítulos y descargas de media en `app/extract.py`.
- `YouTubeTranscriptApi`, faster-whisper local y OpenAI STT/OCR en `app/transcript.py`.
- OpenAI structured chat y reintentos en `app/recipe_builder.py`.
- Apple JWKS/token/revoke mediante `httpx` en `app/apple_auth.py`.
- Los scripts operativos pueden enviar Telegram y backups a B2.

No se encontró una llamada activa a PostHog dentro de `app`, pero analytics y notificaciones se tratarán como bloqueadas por defensa en profundidad.

### Infraestructura documentada que hay que verificar antes de cargar

Según la documentación local, el VPS está descrito como Ubuntu 24.04, 4 vCPU, 8 GB RAM y 75 GB NVMe. El backend tiene límites documentados de 2.5 CPU y 3 GB RAM. PostgreSQL aparece como contenedor separado con PostgreSQL 16 y `max_connections=40` en el tuning documentado, pero el script operativo no aplica límites explícitos de CPU/RAM al contenedor de PostgreSQL. Por tanto, estos valores son hipótesis hasta verificarlos en vivo.

Referencias auditadas:

- [app/config.py](/Users/andrescasillas/Desktop/ReciApp-Server/app/config.py)
- [app/main.py](/Users/andrescasillas/Desktop/ReciApp-Server/app/main.py)
- [app/db.py](/Users/andrescasillas/Desktop/ReciApp-Server/app/db.py)
- [app/pipeline.py](/Users/andrescasillas/Desktop/ReciApp-Server/app/pipeline.py)
- [app/extract.py](/Users/andrescasillas/Desktop/ReciApp-Server/app/extract.py)
- [app/transcript.py](/Users/andrescasillas/Desktop/ReciApp-Server/app/transcript.py)
- [app/recipe_builder.py](/Users/andrescasillas/Desktop/ReciApp-Server/app/recipe_builder.py)
- [Dockerfile](/Users/andrescasillas/Desktop/ReciApp-Server/Dockerfile)
- [stress_extract_ramp.py](/Users/andrescasillas/Desktop/ReciApp-Server/scripts/stress_extract_ramp.py)
- [docker-compose.prod.yml](/Users/andrescasillas/Desktop/Server/deploy/docker-compose.prod.yml)
- [postgres-tune.sql](/Users/andrescasillas/Desktop/Server/deploy/postgres-tune.sql)
- [INFRASTRUCTURE.md](/Users/andrescasillas/Desktop/Server/INFRASTRUCTURE.md)

## 3. Arquitectura de `STRESS_TEST_MODE=true`

El modo de stress será fail-closed: si se detecta una configuración insegura, el backend no arrancará como target de stress.

### Condiciones obligatorias

`STRESS_TEST_MODE=true` exigirá:

1. Una `DATABASE_URL` con nombre/base de datos y credenciales específicas de stress.
2. Un identificador inequívoco del entorno, por ejemplo `stress` en el nombre de la base y del servicio.
3. Secretos de proveedores externos vacíos, ausentes o reemplazados por adaptadores locales.
4. Hosts sintéticos permitidos, por ejemplo `stress-test.local`, sin posibilidad de pasar a extracción real.
5. Un mock local de todas las dependencias que pueda fallar de forma segura.
6. Un `STRESS_RUN_ID` y semilla reproducible para cada ejecución.
7. Desactivación de tareas operativas con efectos externos: notificaciones, backups remotos, webhooks salientes y analytics.
8. Una comprobación de que el target no es el dominio de producción.

### Defensa en profundidad

Además de los guards de aplicación:

- La red del stack de stress tendrá únicamente los servicios necesarios.
- El backend no tendrá ruta de salida a Internet durante la prueba, o se aplicará una política de egress que permita únicamente el acceso imprescindible del propio stack.
- El acceso desde el Mac al backend se hará preferentemente mediante túnel SSH a loopback del VPS, no exponiendo una ruta pública nueva.
- El cliente de carga comprobará el certificado, host, `STRESS_TEST_MODE` y un token de prueba antes de enviar tráfico.
- La base stress estará en un contenedor/volumen separados y tendrá un nombre que impida confundirla con producción.
- El collector guardará evidencia de la configuración efectiva, imagen, commit y migraciones.

La aplicación no deberá interpretar una URL sintética como una URL descargable. El adaptador de stress reconocerá el host sintético antes de cualquier normalización que pueda activar `yt-dlp`, HTTP, oEmbed, subtítulos o media.

## 4. Mock local de IA y dependencias

El mock conservará las etapas y contratos relevantes del pipeline, pero nunca usará red externa ni una API real.

### Perfiles de latencia

Se configurarán perfiles reproducibles para:

- 0, 10, 50, 100, 250 y 500 ms.
- 1, 2, 3, 5 y 10 s.
- Latencia uniforme, aleatoria acotada y distribución realista definida por percentiles.
- Latencia por etapa para distinguir parseo, generación, validación y persistencia.

### Perfiles de fallo

Cada perfil podrá definir porcentajes independientes para:

- Respuesta válida.
- Respuesta lenta.
- Timeout.
- Error transitorio.
- Error permanente.
- Respuesta inválida o incompleta.

Se probarán, como mínimo, 1%, 5%, 10%, 25%, 50% y 100% de fallos, además del perfil 95% normal / 3% lento / 1% timeout / 1% error.

Los timeouts se implementarán en el mock de forma controlada para comprobar cancelación, liberación de slots, workers y conexiones. No se simulará un timeout bloqueante infinito sin un watchdog que pueda detener la prueba.

El mock devolverá recetas válidas según el schema real de producción. Las respuestas inválidas serán deliberadas y etiquetadas para que el reporte distinga rechazo correcto, error interno y dependencia defectuosa.

## 5. Datos sintéticos y dimensiones del workload

Cada request tendrá metadatos de correlación:

- `stress_run_id`.
- `scenario_id`.
- `phase` (`warmup`, `measure`, `cooldown`, `recovery`).
- Semilla y secuencia del generador.
- Tipo de payload, tamaño, URL y resultado esperado.

### URLs

Se generarán URLs únicas deterministas, por ejemplo:

```text
https://stress-test.local/recipe/000001
https://stress-test.local/recipe/000002
```

El generador soportará millones sin cargar todo el dataset en memoria. Se usarán perfiles:

- 100% URLs nuevas.
- 100% repetidas.
- 50% nuevas / 50% repetidas.
- 80% nuevas / 20% repetidas.
- Distribución aleatoria parametrizable.

Las pruebas repetidas estarán separadas de las de capacidad pura para no mezclar deduplicación, cache hits o conflictos únicos con el throughput de creación real.

### Payloads

Se generarán recetas falsas válidas en tamaños:

- Mínimo.
- Pequeño.
- Normal.
- Grande.
- Cercano al límite permitido.
- Inválido por JSON, campos ausentes, URL inválida, duplicado o tamaño excesivo.

El schema se derivará del contrato real y se validará antes de enviar una campaña. El generador registrará bytes de request y response para relacionar payload con red, CPU, RAM, parsing y disco.

### Identidad y repetición

Se usarán usuarios de prueba y perfiles separados. La selección de usuarios será configurable para medir tanto la concurrencia por usuario como la distribución entre usuarios. Los IDs de requests, jobs y recetas serán trazables sin depender de datos de producción.

## 6. Herramienta principal

Se selecciona **k6** como herramienta principal por ser gratuita, reproducible, scriptable, adecuada para rampas, tasas abiertas y escenarios de larga duración, y capaz de emitir métricas JSON/CSV y aplicar thresholds.

Se complementará con un collector ligero en shell/Python/SQL para métricas del VPS, Docker y PostgreSQL. No se instalarán cinco generadores de carga.

Alternativas evaluadas:

- Locust: buena extensibilidad en Python, pero añade un runner/controlador y resulta menos directo para este pipeline con RPS adaptativo.
- Artillery: válido para escenarios HTTP, aunque la instrumentación y búsqueda adaptativa requerirían más piezas propias.
- autocannon: excelente para benchmarks HTTP puntuales, menos completo para la matriz larga y los criterios de aceptación.
- wrk: muy eficiente para throughput puro, pero insuficiente como orquestador de jobs, perfiles y reportes del backend.

Referencias de la herramienta:

- [Resultados de k6](https://grafana.com/docs/k6/latest/get-started/results-output/)
- [Thresholds de k6](https://grafana.com/docs/k6/latest/using-k6/thresholds/)

No se instalará ni ejecutará k6 hasta aprobar el plan y cerrar la implementación de seguridad.

## 7. Observabilidad y correlación

La observabilidad tendrá dos niveles: métricas del cliente y métricas del sistema. Todos los datos compartirán timestamps UTC, `stress_run_id`, `scenario_id` y fases.

### Métricas del cliente y API

Para cada escenario se registrarán:

- RPS enviados y RPS aceptados.
- Recetas creadas por segundo y jobs completados por segundo.
- Requests concurrentes, requests totales y bytes transferidos.
- Success rate y error rate.
- Conteos separados de 2xx, 3xx, 4xx, 5xx y respuestas esperadas por validación/rate limit.
- Timeouts del cliente, del servidor y del mock.
- Latencia media, p50, p90, p95, p99 y máximo.
- Tiempo de aceptación, espera en cola, ejecución, persistencia y polling.
- Queue depth, jobs pendientes, processing, complete y failed.
- Cache hit, deduplicación, conflicto y creación realmente nueva.
- Reintentos, cancelaciones y jobs perdidos.

### Servidor, Docker y proceso

El collector capturará periódicamente:

- CPU y RAM totales del VPS.
- Load average, procesos, threads, file descriptors y conexiones TCP.
- CPU, memoria, PIDs, network I/O y block I/O por contenedor.
- Reinicios, OOM kills, health checks y estado de cada servicio.
- Network I/O de backend y PostgreSQL.
- Disk I/O, latencia de disco y espacio libre.
- Event loop lag, workers, threads y tareas pendientes cuando el runtime lo permita.
- Logs de aplicación con timestamp, correlation ID, job ID, etapa y duración.

Se usarán `docker stats` y herramientas ligeras del sistema (`vmstat`, `mpstat`, `iostat`/`sar` si están disponibles), con intervalos suficientemente pequeños para ver spikes sin producir una carga relevante.

### PostgreSQL

El collector consultará, siempre en la base stress:

- CPU/RAM del contenedor.
- Conexiones activas, idle, idle-in-transaction y waiting.
- Uso del pool de la aplicación: disponible, usado, espera y timeout.
- `pg_stat_activity` y waits por tipo.
- `pg_stat_database`: transacciones, commits, rollbacks, bloques, conflictos y deadlocks.
- `pg_locks`: locks concedidos, esperas y bloqueos por relación.
- Queries por segundo y tiempo de escritura en DB.
- Queries lentas y top SQL, con parámetros anonimizados.
- Tamaño de base, tablas, índices, WAL y crecimiento antes/después.
- Checkpoints, buffers y actividad de vacuum cuando esté disponible.

Se habilitará `pg_stat_statements` únicamente en la instancia stress si resulta compatible y no introduce una diferencia material respecto a la configuración objetivo. Si no está disponible, se usará la evidencia de `pg_stat_activity`, logs y contadores de la aplicación.

### Artefactos por ejecución

Cada ejecución producirá un directorio como:

```text
artifacts/<date>/<stress_run_id>/
  manifest.json
  config.resolved.json
  k6-summary.json
  k6-raw.json
  client-timeseries.csv
  host-metrics.csv
  docker-stats.csv
  postgres-metrics.csv
  backend.log
  postgres.log
  report.html
  charts/
```

El manifest incluirá commit, imagen/digest, migraciones, hardware detectado, límites efectivos, semilla, perfiles, versión del runner y estado de limpieza.

## 8. Modelo común de cada prueba

Ningún resultado se considerará válido si no contiene las cuatro fases:

1. **Preflight:** target correcto, modo stress activo, egress bloqueado, DB correcta, espacio libre, health/readiness y collector funcionando.
2. **Warm-up:** carga suficiente para calentar aplicación, conexiones, cachés y PostgreSQL; sus métricas no entran en el resultado.
3. **Measurement:** carga estable o perfil programado durante la duración definida.
4. **Cooldown y recovery:** detener/reducir carga, observar drenaje, normalización y capacidad de aceptar una request de control.

Cada escenario tendrá configuración versionada de:

- Carga objetivo.
- Concurrencia máxima.
- Duración de warm-up, medición, cooldown y recovery.
- Dataset, tamaño, mix y porcentaje de repetición.
- Latencia/fallos del mock.
- Thresholds de éxito y fallo.
- Política de repetición y semilla.

Para exploración se usará una medición inicial de 60 s, salvo pruebas de burst y baseline. Las pruebas de soak usarán las duraciones solicitadas. Las campañas importantes se repetirán tres veces; un outlier no se ocultará promediando resultados.

## 9. Batería de pruebas

### Fase A: sanity y baseline

- Health/readiness, autenticación, permisos y target.
- 1 usuario, 1 request cada vez.
- Un caso nuevo y un caso repetido.
- Latencia mock 0 ms y latencia nominal.
- Medición de coste mínimo de crear una receta: latencia por etapa, queries, bytes, CPU, RAM y tamaño de DB.
- Validación de que una receta realmente nueva termina creada y no solo aceptada en cola.

### Fase B: concurrencia

Barrido inicial de 1, 2, 5, 10, 25, 50, 100, 250, 500 y 1000+ requests concurrentes, con límites de seguridad.

Se reportarán por separado:

- Requests aceptadas.
- Jobs en cola.
- Jobs ejecutando.
- Recipes realmente creadas.
- Concurrencia de HTTP.
- Concurrencia de slots de extracción.
- Conexiones y espera del pool.

Los rate limits actuales se probarán como una campaña funcional independiente. No se usará accidentalmente el rate limit para declarar capacidad de backend.

### Fase C: RPS adaptativo

Se empezará con una búsqueda geométrica y se afinará automáticamente:

1. Medir un punto bajo.
2. Incrementar RPS mientras el resultado sea estable.
3. Detener el avance al aparecer degradación reproducible.
4. Guardar el último punto estable y el primer punto degradado.
5. Buscar entre ambos con pasos más pequeños o búsqueda binaria.
6. Repetir los puntos candidatos para confirmar.

No se limitará el estudio a valores prefijados. Los resultados determinarán los siguientes RPS.

### Fase D: ramp-up y ramp-down

Ramp-ups de 30 s, 1 min, 5 min, 10 min y 30 min desde cero hasta una carga objetivo segura. Después se reducirá la carga en escalones y se medirá:

- Tiempo hasta que p95/p99 vuelve a la banda estable.
- Tiempo hasta que la cola llega a cero.
- Tiempo hasta que el pool deja de esperar.
- Tiempo hasta CPU, RAM, red y disco normales.
- Errores tardíos o jobs que terminan después de detener la entrada.

### Fase E: spike, burst, wave y random

- Spike: 5→100 RPS, 10→500 RPS, 10→límite estimado y 10→por encima del límite.
- Burst: 10, 50, 100, 500 y 1000 requests casi simultáneas.
- Wave: 10→50→100→20→150→30→200 RPS, ajustado al límite observado.
- Random traffic: inter-arrivals y operaciones impredecibles dentro de un presupuesto de carga.

Se verificará si el sistema rechaza de forma controlada, encola, se recupera o queda degradado.

### Fase F: stress y breakpoint

Incrementar carga hasta que se observe degradación clara o se alcance el guard de seguridad. Se probará el punto encontrado alrededor del límite para identificar:

- p95/p99 excesivo.
- Timeouts.
- 5xx.
- CPU o RAM saturadas.
- Pool agotado.
- PostgreSQL saturado.
- Locks o queries lentas.
- Crecimiento no acotado de cola.
- Reinicios, OOM o pérdida de jobs.

### Fase G: soak/endurance

Mantener cargas estables durante 1 min, 5 min, 15 min, 30 min y 1 h. Las pruebas de varias horas quedarán condicionadas a que no haya riesgo para el VPS y a la aprobación específica.

Buscar memory leaks, conexiones que no se liberan, degradación progresiva, acumulación de jobs, crecimiento de latencia, WAL, logs, tablas, índices y disco.

### Fase H: workload mixto

Distribución configurable de:

- Creación de recetas nuevas.
- Lectura de recetas existentes.
- Búsqueda.
- Polling de jobs.
- Duplicados y cache hits.
- Usuarios nuevos y existentes.
- Requests inválidas.
- Payloads pequeños, normales y grandes.

La distribución se fijará por semilla y se reportará para que dos ejecuciones sean comparables.

### Fase I: aislamiento por componente

- **API-only:** mock de PostgreSQL y de IA cuando sea posible para medir el límite puro de HTTP, validación, serialización y workers.
- **Database-heavy:** IA y latencia externa a 0 ms, URLs nuevas y operaciones reales contra PostgreSQL stress para hallar el throughput de persistencia.
- **Full-backend:** API real, PostgreSQL real de stress y mocks locales; será el benchmark principal.
- **Slow dependency:** 500 ms, 1 s, 3 s, 5 s y 10 s, midiendo slots, workers, RAM, pool y throughput.

### Fase J: fallos de dependencia

- 1%, 5%, 10%, 25%, 50% y 100% de errores.
- Timeout storm con muchas llamadas lentas simultáneas.
- Respuestas inválidas mezcladas con respuestas correctas.
- Comprobación de retries, backoff, cancelación, liberación de slots y continuidad del servicio.

### Fase K: invalid requests

JSON incorrecto, campos ausentes, URLs inválidas, payload demasiado grande, duplicados y combinaciones inválidas. Se medirá que el rechazo sea barato y estable, sin consultas o jobs innecesarios.

### Fase L: cold versus warm

Comparar:

- Backend recién iniciado frente a backend caliente.
- PostgreSQL recién iniciado frente a PostgreSQL caliente.
- Caché vacía frente a caché llena.
- Pool recién creado frente a pool estabilizado.
- Primera request frente a steady state.

Para PostgreSQL se reiniciará únicamente el contenedor/instancia stress. No se ejecutarán `drop_caches` ni acciones equivalentes sobre el host compartido.

## 10. Algoritmo de breaking point

El runner calculará tres hitos distintos:

1. **Stable limit:** máximo nivel que cumple thresholds en tres repeticiones.
2. **Degradation starts:** primer nivel donde una métrica se deteriora de forma reproducible frente al nivel anterior estable.
3. **Breaking point:** primer nivel que viola un criterio operativo, aunque el proceso siga vivo.

Los criterios iniciales serán configurables y se ajustarán tras el baseline:

- Sin reinicio, OOM, pérdida de jobs ni pérdida de acceso de administración.
- Error rate y 5xx por debajo del umbral acordado.
- Timeouts por debajo del umbral acordado.
- p95/p99 dentro del límite de producto y sin crecimiento sostenido.
- Cola y espera del pool acotadas; la cola debe drenar durante cooldown.
- Sin locks o queries lentas que crezcan sin límite.
- Headroom mínimo de CPU, RAM, conexiones y disco.
- Readiness y una request de control correctas después de la prueba.

La búsqueda usará pasos grandes al explorar, bracket entre estable/degradado y pasos pequeños alrededor del límite. El runner no continuará si un guard crítico se activa.

## 11. Recovery test

Después de cada prueba destructiva o por encima del límite:

1. Detener la entrada nueva.
2. Mantener el collector activo.
3. Medir cola, jobs processing, slots, pool, conexiones y errores.
4. Esperar a que CPU, RAM, locks y latencia bajen a la banda estable.
5. Confirmar que la cola llega a cero o que los trabajos restantes se clasifican correctamente.
6. Enviar una request sintética de control.
7. Registrar el tiempo desde stop-load hasta recuperación.

Se considerará recuperado cuando haya tres muestras consecutivas dentro de la banda normal, no haya cola pendiente no explicada, no existan locks anómalos y la request de control cumpla el threshold. Habrá un timeout de recovery configurable para evitar esperar indefinidamente.

## 12. Matriz inteligente y reducción de combinaciones

La matriz completa será:

```text
tipo de carga × concurrencia × RPS × duración × latencia mock
× tamaño de receta × mix de requests × estado cold/warm
```

No se ejecutará el producto cartesiano completo. La estrategia será:

- Exploración corta con payload normal, URLs nuevas y latencia 0 ms.
- Aislar primero el límite de API, DB y dependencia lenta.
- Usar el límite observado para seleccionar solo puntos cercanos.
- Cambiar una dimensión cada vez en la fase diagnóstica.
- Combinar dimensiones solo en los puntos estables, degradados y de producción representativos.
- Repetir tres veces únicamente los escenarios clave.
- Ejecutar soak solo en cargas ya calificadas como estables.

Se guardará una decisión de inclusión/exclusión por escenario para saber por qué una combinación no se ejecutó.

## 13. Automatización propuesta

El punto de entrada será:

```bash
./stress-test.sh
```

Flujo previsto:

1. Validar branch/commit y configuración local.
2. Validar `STRESS_TEST_MODE=true` en el target.
3. Validar que los proveedores externos están bloqueados.
4. Validar target, túnel, health/readiness, espacio y permisos.
5. Preparar la base stress y aplicar migraciones.
6. Generar perfiles y datos sintéticos bajo demanda.
7. Arrancar collector y captura de logs.
8. Ejecutar sanity y baseline.
9. Ejecutar exploración adaptativa de concurrencia/RPS.
10. Buscar automáticamente stable limit, degradation starts y breaking point.
11. Ejecutar escenarios focalizados alrededor de esos niveles.
12. Ejecutar latencias, fallos, workloads mixtos, cold/warm, soak y recovery.
13. Generar CSV, JSON, tablas y gráficas.
14. Generar informe comparable con diagnóstico del primer cuello de botella.
15. Ejecutar pre-cleanup y mostrar exactamente qué recursos temporales quedan.
16. Limpiar solo tras confirmación/guard explícito.

La automatización será idempotente: un fallo debe permitir reanudar o marcar la ejecución como incompleta sin mezclar artefactos de runs anteriores.

## 14. Criterio para identificar el cuello de botella

El reporte no declarará un culpable solo por correlación visual. Para cada candidato se buscará evidencia temporal y causal:

- CPU de backend alta con pool y PostgreSQL holgados: límite de aplicación/serialización/worker.
- CPU o locks de PostgreSQL altos, queries lentas y pool esperando: límite de DB o diseño de queries.
- Pool agotado con CPU baja: tamaño de pool, slots, latencia de dependencia o transacciones retenidas.
- RAM creciente con throughput estable o decreciente: posible leak, cola o buffers.
- Latencia proporcional a mock y slots ocupados: dependencia lenta/backpressure.
- Red o disco saturados: payload, logs, WAL o almacenamiento.
- 4xx altos con recursos holgados: rate limit/admission/validación, no capacidad física.
- 5xx y timeouts al crecer la cola: falta de backpressure, timeout o recuperación.

Cada conclusión incluirá métrica, intervalo temporal, escenario, repetición y limitaciones de la evidencia.

## 15. Informe final comparable

El informe tendrá un resumen ejecutivo y un apéndice reproducible. Como mínimo mostrará:

```text
Maximum stable throughput: <recipes/s>
Maximum concurrency: <requests>
p50 / p95 / p99: <values>
Error rate: <percentage>
Degradation starts: <recipes/s>
Breaking point: <recipes/s>
CPU / RAM at breaking point: <values>
PostgreSQL connections / pool: <values>
Primary bottleneck: <component>
Recovery time: <seconds>
```

Gráficas obligatorias:

- RPS vs latencia.
- RPS vs error rate.
- RPS vs CPU.
- RPS vs RAM.
- Concurrencia vs latencia.
- Latencia mock vs throughput.
- Queue depth y pool wait durante tiempo.
- Queries/s, locks y DB write time durante tiempo.
- Recovery timeline después de saturación.

Tablas obligatorias:

- Todos los escenarios y repeticiones.
- Thresholds y resultado pass/fail.
- Recetas realmente creadas frente a requests aceptadas.
- Métricas máximas, medias y percentiles.
- Estado cold/warm, dataset y mock profile.
- Errores clasificados por capa.

## 16. Conversión de resultados a límites seguros de producción

No se copiará directamente el breaking point a producción. El límite operativo se elegirá como el menor límite relevante entre:

- Full-backend con workload representativo.
- DB-heavy si la creación real es DB-bound.
- Slow dependency si la IA puede degradarse.
- Soak al nivel sostenido.
- Concurrency y pool.
- Capacidad de recovery.

El resultado final definirá explícitamente:

- Recetas/segundo y recetas/minuto seguros.
- RPS y concurrencia máxima recomendada.
- Slots de extracción y workers.
- Profundidad máxima de cola.
- Tamaño de pool y margen de conexiones PostgreSQL.
- Timeouts, retries, backoff y cancelación.
- Rate limits globales, por IP, por usuario y por endpoint.
- Política de admisión y backpressure.
- Respuesta para request inmediata, request en cola, cola llena y retry posterior.
- Qué operaciones son síncronas y cuáles asíncronas.
- Tiempo de recovery esperado y alerta operativa.

La recomendación incluirá margen de seguridad y distinguirá entre límite de prueba, límite sostenible y límite de producto.

## 17. Admisión, cola y experiencia de cliente

El flujo que se medirá y, si hace falta, se ajustará antes del benchmark final será:

```text
request → rate limit → admission control → queue → worker/slot
        → dependencia mock/real aislada → PostgreSQL → polling/result
```

El sistema debe distinguir:

- Request ejecutándose ahora.
- Request aceptada y en cola.
- Request rechazada por límite de frecuencia.
- Request rechazada porque la cola está llena.
- Request fallida por dependencia.
- Request reintentable.

El reporte verificará que el usuario no recibe un éxito prematuro que se pierda después y que la interfaz puede mostrar posición aproximada, estado, retry-after o error explicable sin revelar detalles internos.

## 18. Fases de implementación posteriores a la aprobación

### Fase 1 — Instrumentación y guards

Implementar `STRESS_TEST_MODE`, egress fail-closed, DB separada, run IDs, timestamps de jobs, métricas de pool, mock local y logs correlacionados.

### Fase 2 — Runner y generación

Crear configuración versionada, generador de URLs/payloads, escenarios k6, perfiles de latencia/fallo y collector del host/Docker/PostgreSQL.

### Fase 3 — Verificación local

Ejecutar únicamente validaciones unitarias, contract tests, lint/type checks y una prueba local mínima del modo stress. Confirmar que no sale tráfico externo.

### Fase 4 — Preflight del VPS

Verificar en modo read-only target, imagen, límites efectivos, red, egress, alertas, espacio, DB, extensiones, pool y health checks.

### Fase 5 — Campañas

Ejecutar sanity, baseline, exploración adaptativa, breakpoint, pruebas focalizadas, fallos, cold/warm, soak y recovery.

### Fase 6 — Informe y limpieza

Generar reporte, revisar evidencia, proponer límites. Eliminar volumen/stack stress solo después de confirmar el inventario exacto de recursos y autorizar la acción.

## 19. Entregables

- `STRESS_TEST_MODE` fail-closed.
- Mock local de IA y dependencias con perfiles configurables.
- Generador de datos sintéticos reproducible.
- `stress-test.sh` con preflight, ejecución, búsqueda adaptativa, reportes y guardas.
- Scripts k6 para baseline, concurrency, RPS, ramp, spike, burst, wave, random, mixed, soak y failure injection.
- Collector de host, Docker y PostgreSQL.
- Esquema/tabla de telemetría stress o alternativa equivalente sin contaminar producción.
- Report generator con JSON, CSV, HTML y gráficas.
- Runbook de seguridad, recuperación y limpieza.
- Informe por ejecución y resumen comparativo entre commits/configuraciones.

## 20. Gate de aprobación

La siguiente acción será únicamente implementar este plan, y después verificarlo localmente. Para comenzar hará falta aprobación explícita del plan.

Quedan fuera de esta aprobación implícita:

- Ejecutar carga contra el VPS.
- Tocar producción.
- Crear o borrar la base/volumen stress remoto.
- Instalar dependencias en el VPS.
- Desplegar cambios.
- Activar proveedores externos.

La primera meta de aceptación será una ejecución pequeña, aislada y demostrablemente sin egress externo. Solo después se habilitarán los escenarios de capacidad.
