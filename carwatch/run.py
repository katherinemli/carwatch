"""Orquestacion de una corrida. Poco invasiva por diseno."""
import json
import os
import urllib.error
from datetime import datetime, timedelta, timezone

from . import db, parsers
from .fetch import BotChallenge, BudgetExhausted, PoliteFetcher, RobotsDenied


def _now():
    return datetime.now(timezone.utc)


def last_ok_run(con, dealer_id):
    row = con.execute("SELECT started_at FROM runs WHERE dealer_id=? AND ok=1 ORDER BY started_at DESC LIMIT 1",
                      (dealer_id,)).fetchone()
    if not row:
        return None
    try:
        return datetime.fromisoformat(row["started_at"])
    except Exception:
        return None


def due(con, dealer, force=False):
    if not dealer.get("enabled", True):
        return False, "deshabilitado en dealers.json"
    plat = dealer.get("platform")
    if plat == "blocked":
        return False, "bloqueado por anti-bot: revision manual"
    if plat == "forbidden":
        return False, "robots.txt lo prohibe: no se scrapea"
    if plat == "manual":
        return False, "demasiado grande para barrer con respeto: busqueda manual"
    if force:
        return True, "forzado"
    cad = int(dealer.get("cadence_days") or 1)
    if cad <= 0:
        return False, "cadencia 0"
    last = last_ok_run(con, dealer["id"])
    if last is None:
        return True, "primera corrida"
    age_days = (_now() - last).total_seconds() / 86400.0
    if age_days + 0.05 >= cad:
        return True, f"ultima hace {age_days:.1f}d (cadencia {cad}d)"
    return False, f"al dia (hace {age_days:.1f}d de {cad}d)"


def detect_platform(fetcher, log):
    try:
        body, _ = fetcher.get("/")
    except Exception as exc:
        log(f"    no se pudo abrir la portada: {exc}")
        return None
    low = body.lower()
    if "sm360" in low or "showroom360" in low:
        return "sm360"
    if "d2cmedia" in low or "usedsrp" in low:
        return "d2c"
    return None


# --------------------------------------------------------------------------

def run_d2c(con, dealer, fetcher, log):
    """Recorre el inventario por paginas SEO marca-modelo: rutas limpias, sin
    query strings, sin tocar la paginacion JS."""
    seen = {}
    entries = dealer.get("entry", "/used/search.html")
    if isinstance(entries, str):
        entries = [entries]
    entries = entries + [e for e in ("/used/search.html", "/occasion/recherche.html",
                                     "/occasion/inventaire/recherche.html", "/inventaire.html")
                         if e not in entries]
    body, unchanged, used_entry = None, False, None
    for cand in entries:
        try:
            body, unchanged = fetcher.get(cand)
        except (RobotsDenied, urllib.error.HTTPError):
            continue
        if parsers.parse_d2c(body, fetcher.base) or parsers.d2c_seo_links(body):
            used_entry = cand
            break
    if used_entry is None:
        raise RuntimeError("no se encontro una pagina de inventario usada valida")
    if used_entry != entries[0]:
        log(f"    entrada util: {used_entry}")
    n_unchanged = 1 if unchanged else 0
    for card in parsers.parse_d2c(body, fetcher.base):
        seen[card["vehicle_key"]] = card

    links = parsers.d2c_seo_links(body)
    log(f"    {len(seen)} en la portada del inventario, {len(links)} paginas marca-modelo por recorrer")
    for link in links:
        try:
            page, unch = fetcher.get(link)
        except BudgetExhausted as exc:
            log(f"    {exc} — se corta aqui, se sigue la proxima corrida")
            break
        except RobotsDenied as exc:
            log(f"    saltada: {exc}")
            continue
        except urllib.error.HTTPError as exc:
            log(f"    {link}: HTTP {exc.code}")
            continue
        if unch:
            n_unchanged += 1
        for card in parsers.parse_d2c(page, fetcher.base):
            seen.setdefault(card["vehicle_key"], card)
    return list(seen.values()), [], n_unchanged


def run_sm360(con, dealer, fetcher, log, config):
    """Sitemap (1 peticion) para saber QUE existe, y solo bajamos las fichas
    que importan. El resto se 'toca' sin descargar."""
    sm = dealer.get("sitemap", "/en/sitemap-xml")
    xml, _ = fetcher.get(sm)
    urls = parsers.sm360_sitemap_urls(xml, dealer.get("used_url_marker", "used-inventory"))
    log(f"    sitemap: {len(urls)} vehiculos usados listados")

    known = db.known_keys(con, dealer["id"])
    yellow = config["filters"]["price_yellow_max"]
    watch_ceiling = yellow * 1.8   # margen para cazar bajadas hacia tu rango

    def key_of(u):
        import re
        m = __import__("re").search(r"-id(\d+)$", u)
        return f"sm360:{m.group(1)}" if m else f"sm360:{u}"

    new_urls, watch_urls, rest = [], [], []
    for u in urls:
        k = key_of(u)
        if k not in known:
            new_urls.append(u)
        else:
            p = known[k]["price"]
            if p is None or p <= watch_ceiling:
                watch_urls.append(u)
            else:
                rest.append((known[k]["last_seen"] or "", u))

    rest.sort()                       # los mas rancios primero
    rotate = [u for _, u in rest[:12]]  # muestreo rotatorio del inventario caro
    to_fetch = new_urls + watch_urls + rotate
    touched_only = [key_of(u) for u in urls if u not in set(to_fetch)]

    log(f"    a descargar: {len(new_urls)} nuevos + {len(watch_urls)} en seguimiento + {len(rotate)} rotativos "
        f"({len(touched_only)} solo se marcan como presentes)")

    out = []
    n_unchanged = 0
    for u in to_fetch:
        try:
            page, unch = fetcher.get(u)
        except BudgetExhausted as exc:
            log(f"    {exc} — se corta aqui, se sigue la proxima corrida")
            break
        except RobotsDenied as exc:
            log(f"    saltada: {exc}")
            continue
        except urllib.error.HTTPError as exc:
            log(f"    {u}: HTTP {exc.code}")
            continue
        if unch:
            n_unchanged += 1
        rec = parsers.parse_sm360_vdp(page, u)
        if rec:
            out.append(rec)
    return out, touched_only, n_unchanged


# --------------------------------------------------------------------------

def run_dealer(con, dealer, config, cache_dir, log, force=False):
    ok, why = due(con, dealer, force)
    if not ok:
        log(f"  · {dealer['name']}: {why}")
        return None
    log(f"  → {dealer['name']} ({why})")

    pol = config["politeness"]
    fetcher = PoliteFetcher(
        dealer["base"], cache_dir, contact=config.get("contact", ""),
        min_delay=pol["min_delay_seconds"], timeout=pol["timeout_seconds"],
        budget=pol["max_requests_per_dealer_per_run"],
        respect_crawl_delay=pol["respect_robots_crawl_delay"], log=log)

    run_id, started_at = db.start_run(con, dealer["id"])
    platform = dealer.get("platform")
    try:
        log(f"    robots.txt: crawl-delay efectivo {fetcher.effective_delay:.0f}s"
            + (" (sin robots.txt, vamos extra lento)" if fetcher.robots_missing else ""))
        if platform == "auto":
            platform = detect_platform(fetcher, log) or "sm360"
            log(f"    plataforma detectada: {platform}")

        if platform == "d2c":
            records, touched, unchanged = run_d2c(con, dealer, fetcher, log)
        elif platform == "sm360":
            records, touched, unchanged = run_sm360(con, dealer, fetcher, log, config)
        else:
            raise RuntimeError(f"plataforma desconocida: {platform}")

        events = {"NEW": 0, "PRICE_DROP": 0, "PRICE_UP": 0, "BACK": 0}
        for rec in records:
            _, kind = db.upsert(con, dealer["id"], rec)
            if kind in events:
                events[kind] += 1
        db.touch(con, dealer["id"], touched)

        total_present = len(records) + len(touched)
        gone = db.mark_disappeared(con, dealer["id"], started_at, total_present)

        db.finish_run(con, run_id, True, total_present, fetcher.used, unchanged,
                      note=f"nuevos={events['NEW']} bajadas={events['PRICE_DROP']} idos={len(gone)}")
        log(f"    ✓ {total_present} vehiculos · {fetcher.used} peticiones · "
            f"{events['NEW']} nuevos · {events['PRICE_DROP']} bajadas de precio · {len(gone)} ya no figuran")
        return {"dealer": dealer["id"], "ok": True, "n": total_present, "requests": fetcher.used,
                "events": events, "gone": len(gone)}

    except BotChallenge as exc:
        db.finish_run(con, run_id, False, 0, fetcher.used, 0, note=f"anti-bot: {exc}")
        log(f"    ⚠ {exc}")
        log("      No se intenta esquivar. Marca este dealer como 'blocked' en dealers.json y revisalo a mano.")
        return {"dealer": dealer["id"], "ok": False, "blocked": True, "error": str(exc)}
    except Exception as exc:
        db.finish_run(con, run_id, False, 0, fetcher.used, 0, note=f"error: {exc}")
        log(f"    ✗ error: {exc}")
        return {"dealer": dealer["id"], "ok": False, "error": str(exc)}


# --------------------------------------------------------------------------

def autotune(con, dealers, config, log):
    """Sube o baja la frecuencia segun lo que cada dealer haya producido de verdad."""
    a = config.get("adaptive", {})
    if not a.get("enabled"):
        return dealers
    now = _now()
    changed = []
    for d in dealers:
        if not d.get("enabled") or d.get("platform") == "blocked":
            continue
        first = con.execute("SELECT MIN(started_at) AS m FROM runs WHERE dealer_id=? AND ok=1",
                            (d["id"],)).fetchone()
        if not first or not first["m"]:
            continue
        try:
            age_days = (now - datetime.fromisoformat(first["m"])).total_seconds() / 86400.0
        except Exception:
            continue

        since_green = (now - timedelta(days=a["promote_if_green_within_days"])).isoformat()
        recent_hits = con.execute(
            "SELECT COUNT(*) AS c FROM listings WHERE dealer_id=? AND disappeared_at IS NULL "
            "AND price IS NOT NULL AND price <= ? AND transmission='AUTOMATIC' AND last_seen >= ?",
            (d["id"], config["filters"]["price_yellow_max"], since_green)).fetchone()["c"]

        old = d.get("cadence_days")
        if recent_hits > 0 and old != a["promote_to_cadence_days"]:
            d["cadence_days"] = a["promote_to_cadence_days"]
            changed.append(f"{d['name']}: cada {old}d → {d['cadence_days']}d (tiene {recent_hits} en tu rango)")
        elif recent_hits == 0 and age_days >= a["demote_if_no_candidate_days"] and old != a["demote_to_cadence_days"]:
            ever = con.execute(
                "SELECT COUNT(*) AS c FROM listings WHERE dealer_id=? AND price IS NOT NULL AND price <= ?",
                (d["id"], config["filters"]["price_yellow_max"])).fetchone()["c"]
            if ever == 0:
                d["cadence_days"] = a["demote_to_cadence_days"]
                changed.append(f"{d['name']}: cada {old}d → {d['cadence_days']}d "
                               f"({int(age_days)}d observado sin un solo auto en tu rango)")
    for c in changed:
        log(f"  ajuste · {c}")
    return dealers
