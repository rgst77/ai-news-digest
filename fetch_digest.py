#!/usr/bin/env python3
"""
fetch_digest.py

Proyecto: Digest diario de noticias de IA.

Arquitectura (fan-out / merge):
  1. FAN-OUT: lee varios feeds RSS de forma independiente (cada fuente es un nodo).
  2. FILTRO: se queda solo con entradas publicadas dentro de la ventana de horas
     indicada (por defecto 26h, para cubrir huecos entre ejecuciones).
  3. MERGE: combina todas las entradas en un único digest, agrupado por categoría,
     y lo guarda como Markdown en output/digest_YYYY-MM-DD.md.

No llama a ningún modelo de IA: solo recolecta y filtra. El resumen/síntesis final
se hace aparte (por ejemplo, pidiéndoselo a Claude), tal y como se planteó el
proyecto originalmente, para no depender de una API key de pago.

Además del filtro por fecha, aplica un filtro de RELEVANCIA por palabras clave
(ver priorities.yaml): descarta ruido evidente (listicles genéricos) y prioriza
lo que menciona a los labs/temas que dominan la actualidad, quedándose solo con
los N items mejor puntuados por categoría.

Uso:
    python3 fetch_digest.py [--hours 26] [--feeds feeds.yaml] [--priorities priorities.yaml] [--max-per-category 5] [--out output]
"""

import argparse
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import feedparser
import yaml


def load_feeds(path: str):
    with open(path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)
    return data.get("feeds", [])


def load_priorities(path: str):
    """Carga labs/themes/noise desde priorities.yaml. Si no existe, no se filtra nada."""
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
    except FileNotFoundError:
        return {"labs": [], "themes": [], "noise": []}
    return {
        "labs": data.get("labs", []) or [],
        "themes": data.get("themes", []) or [],
        "noise": data.get("noise", []) or [],
    }


def score_item(item, priorities):
    """Puntúa un item por relevancia. Devuelve None si hay que descartarlo (ruido)."""
    title_lower = item["title"].lower()

    for pattern in priorities["noise"]:
        if pattern.lower() in title_lower:
            return None

    score = 0
    for lab in priorities["labs"]:
        if lab.lower() in title_lower:
            score += 3
    for theme in priorities["themes"]:
        if theme.lower() in title_lower:
            score += 1
    return score


def entry_datetime(entry):
    """Devuelve un datetime timezone-aware para una entrada de feedparser, o None."""
    for field in ("published_parsed", "updated_parsed"):
        value = getattr(entry, field, None)
        if value:
            return datetime(*value[:6], tzinfo=timezone.utc)
    return None


def fetch_one_feed(feed_cfg, cutoff, timeout=15):
    """FAN-OUT: procesa una fuente de forma independiente.
    Devuelve (nombre_fuente, lista_de_items, error_o_None).
    """
    name = feed_cfg["name"]
    url = feed_cfg["url"]
    category = feed_cfg.get("category", "General")

    try:
        parsed = feedparser.parse(url, request_headers={"User-Agent": "ai-news-digest/1.0"})
        if parsed.bozo and not parsed.entries:
            return name, [], f"Error al parsear el feed: {parsed.bozo_exception}"

        items = []
        for entry in parsed.entries:
            dt = entry_datetime(entry)
            # Si no hay fecha, se incluye igualmente (mejor mostrar de más que perder noticias)
            if dt is not None and dt < cutoff:
                continue
            items.append(
                {
                    "title": entry.get("title", "(sin título)").strip(),
                    "link": entry.get("link", ""),
                    "published": dt.isoformat() if dt else None,
                    "source": name,
                    "category": category,
                }
            )
        return name, items, None
    except Exception as exc:  # noqa: BLE001 - queremos capturar cualquier fallo de red/parseo
        return name, [], str(exc)


def dedupe(items):
    """Elimina duplicados por título normalizado (varias fuentes pueden citar la misma noticia)."""
    seen = set()
    unique = []
    for item in items:
        key = item["title"].strip().lower()
        if key in seen:
            continue
        seen.add(key)
        unique.append(item)
    return unique


def build_digest_markdown(items, run_date, hours):
    by_category = {}
    for item in items:
        by_category.setdefault(item["category"], []).append(item)

    lines = [f"# Digest de noticias de IA — {run_date.isoformat()}", ""]
    lines.append(f"_Ventana: últimas {hours} horas. Total de items: {len(items)}._")
    lines.append("")

    if not items:
        lines.append("No se encontraron noticias nuevas en esta ventana.")
        return "\n".join(lines)

    for category, cat_items in sorted(by_category.items()):
        lines.append(f"## {category}")
        lines.append("")
        for item in sorted(cat_items, key=lambda x: x.get("score", 0), reverse=True):
            lines.append(f"- **{item['title']}** ({item['source']}) — {item['link']}")
        lines.append("")

    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description="Fan-out + merge de feeds RSS de IA en un digest diario.")
    parser.add_argument("--hours", type=int, default=26, help="Ventana de horas hacia atrás a incluir (default: 26)")
    parser.add_argument("--feeds", type=str, default=str(Path(__file__).parent / "feeds.yaml"))
    parser.add_argument("--priorities", type=str, default=str(Path(__file__).parent / "priorities.yaml"))
    parser.add_argument("--max-per-category", type=int, default=5, help="Máximo de items a mostrar por categoría tras filtrar (default: 5)")
    parser.add_argument("--out", type=str, default=str(Path(__file__).parent / "output"))
    args = parser.parse_args()

    feeds_cfg = load_feeds(args.feeds)
    if not feeds_cfg:
        print("No hay feeds configurados en feeds.yaml", file=sys.stderr)
        sys.exit(1)

    priorities = load_priorities(args.priorities)

    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(hours=args.hours)

    all_items = []
    errors = []

    # FAN-OUT: cada feed se procesa de forma independiente (secuencial aquí por
    # simplicidad; con pocos feeds no hace falta paralelizar).
    for feed_cfg in feeds_cfg:
        name, items, error = fetch_one_feed(feed_cfg, cutoff)
        print(f"[{name}] {len(items)} items nuevos" + (f" -- ERROR: {error}" if error else ""))
        all_items.extend(items)
        if error:
            errors.append((name, error))

    # MERGE
    all_items = dedupe(all_items)
    total_before_filter = len(all_items)

    # FILTRO DE RELEVANCIA: descarta ruido evidente y puntúa por relevancia
    scored_items = []
    discarded_noise = 0
    for item in all_items:
        score = score_item(item, priorities)
        if score is None:
            discarded_noise += 1
            continue
        item["score"] = score
        scored_items.append(item)

    # Nos quedamos solo con los N mejor puntuados de cada categoría
    by_category = {}
    for item in scored_items:
        by_category.setdefault(item["category"], []).append(item)

    final_items = []
    for cat_items in by_category.values():
        cat_items.sort(key=lambda x: x["score"], reverse=True)
        final_items.extend(cat_items[: args.max_per_category])

    print(
        f"\nFiltro de relevancia: {total_before_filter} items -> "
        f"{discarded_noise} descartados por ruido -> {len(final_items)} tras quedarnos "
        f"con el top {args.max_per_category} por categoría"
    )

    digest_md = build_digest_markdown(final_items, now.date(), args.hours)

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"digest_{now.date().isoformat()}.md"
    out_path.write_text(digest_md, encoding="utf-8")

    print(f"\nDigest guardado en: {out_path}")
    if errors:
        print("\nAvisos:")
        for name, error in errors:
            print(f"  - {name}: {error}")


if __name__ == "__main__":
    main()
