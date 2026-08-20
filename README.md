# AI News Digest

Proyecto para generar un digest diario de noticias de IA a partir de varios feeds RSS
(fan-out), combinados en un único resumen (merge).

## Estructura

- `feeds.yaml` — lista de fuentes RSS a seguir (edítala para añadir/quitar fuentes).
- `fetch_digest.py` — script que lee todos los feeds, filtra por fecha, deduplica y
  guarda el digest en `output/digest_YYYY-MM-DD.md`. No usa ninguna API de pago: solo
  recolecta y filtra titulares.
- `requirements.txt` — dependencias (`feedparser`, `PyYAML`).
- `.github/workflows/digest.yml` — workflow de GitHub Actions listo para usar (cron
  diario gratis) cuando subas el proyecto a tu propio repo.

## Cómo correrlo en local o en GitHub Actions

```bash
pip install -r requirements.txt
python3 fetch_digest.py            # ventana por defecto: últimas 26 horas
```

Esto funciona sin cambios tanto en tu propio ordenador como en GitHub Actions, porque
ambos tienen acceso normal a internet.

## Nota importante sobre esta sesión de Cowork

Al probar el script *dentro* de este entorno en la nube de Claude, las peticiones de red
salientes desde `bash`/Python están restringidas a una lista blanca de dominios (npm,
PyPI, GitHub, Google Cloud, etc.) por motivos de seguridad del sandbox. Los feeds RSS
(arxiv.org, openai.com, deepmind.google, techcrunch.com) no están en esa lista, así que
`fetch_digest.py` no puede alcanzar internet libremente desde aquí — devuelve error
`403 Tunnel connection failed`.

Verifiqué la lógica del script contra un feed RSS local de prueba (sin red) y funciona
correctamente: filtra por ventana de horas y deduplica bien.

Para la ejecución automática **de verdad** hay dos caminos:

1. **GitHub Actions** (recomendado a medio plazo): sube esta carpeta a un repo tuyo, y
   el workflow ya incluido corre gratis cada día a las 8 AM (hora de Auckland). Acceso a
   internet normal, sin restricciones.
2. **Scheduled task de Cowork** (lo que se ha configurado ya, ver más abajo): en vez de
   ejecutar este script literal, la tarea programada usa la herramienta `WebFetch` de
   Claude (que sí tiene acceso a la web) para leer los mismos feeds y generar el digest
   con la misma lógica de fan-out + merge, y además añade un resumen sintetizado por
   Claude (incluido en el plan, sin coste extra de API).

Cuando quieras moverte a GitHub Actions, este script ya está listo — no hay que tocar
nada.

## Fuentes cubiertas

Ver `feeds.yaml`. Nota: Anthropic no publica un feed RSS público en anthropic.com/news
a día de hoy (comprobado: da 404); si lo añaden en el futuro, se puede sumar a la lista.
