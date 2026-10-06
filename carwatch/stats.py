"""Estadistica para comparar concesionarias y para leer sus MOVIMIENTOS.

Por que existe este fichero
---------------------------
"Un dealer tiene 111 autos y 6 candidatos; otro tiene 59 y 3. ¿Cual es mejor?"

6/111 = 5,4 %  ·  3/59 = 5,1 %

Puestos asi parecen casi iguales, y lo son: la diferencia (0,3 puntos) es MUCHO
mas pequena que el ruido que tienen esos numeros. Con solo 6 y 3 aciertos, si
manana aparece o desaparece un coche, el orden se da la vuelta. Comparar dos
porcentajes crudos sin mirar de cuantos autos salen es la trampa clasica.

Aqui se hace de dos maneras, las dos honestas:

1. TASA AJUSTADA (Beta-binomial / "encogimiento"). Un dealer del que sabemos
   poco no se juzga solo por sus datos: se le mezcla con la media de todos los
   dealers, con un peso equivalente a `prior_strength` autos. Con 500 autos
   observados sus datos mandan casi del todo; con 20, apenas mueven la aguja.
   Es exactamente "no me creo un 50 % sacado de 2 coches".

2. INTERVALO DE CONFIANZA (Wilson). El rango de tasas compatibles con lo
   observado. Wilson y no el de toda la vida (p ± z·sqrt(p(1-p)/n)) porque con
   proporciones pequenas y n moderado ese ultimo da barbaridades, incluso
   limites negativos.

Si dos intervalos se solapan mucho, la respuesta correcta a "¿cual es mejor?"
es NO SE SABE, y eso es lo que dibuja la web.
"""
import math
from collections import defaultdict
from datetime import datetime, timedelta, timezone

# z para los niveles de confianza que tiene sentido usar aqui.
_Z = {0.80: 1.2816, 0.90: 1.6449, 0.95: 1.9600, 0.99: 2.5758}


def z_for(confidence):
    return _Z.get(round(float(confidence), 2), 1.9600)


def wilson_interval(x, n, z=1.96):
    """Intervalo de Wilson para una proporcion. Devuelve (lo, hi) en 0..1.

    Con n=0 devuelve (0, 1): no sabemos nada, y eso es la respuesta correcta.
    """
    if n <= 0:
        return 0.0, 1.0
    p = x / n
    z2 = z * z
    denom = 1.0 + z2 / n
    centre = p + z2 / (2 * n)
    margin = z * math.sqrt(p * (1 - p) / n + z2 / (4 * n * n))
    lo = (centre - margin) / denom
    hi = (centre + margin) / denom
    return max(0.0, lo), min(1.0, hi)


def shrunk_rate(x, n, prior_mean, strength):
    """Tasa 'encogida' hacia la media global.

    (aciertos + k·media) / (autos + k). Con k = strength. Es la media posterior
    de una Beta(k·m, k·(1-m)) actualizada con lo observado: la version formal de
    "hazle caso a este dealer en proporcion a cuantos autos le he visto".
    """
    if n <= 0:
        return prior_mean
    return (x + strength * prior_mean) / (n + strength)


def _median(values):
    vals = sorted(v for v in values if v is not None)
    if not vals:
        return None
    mid = len(vals) // 2
    return float(vals[mid]) if len(vals) % 2 else (vals[mid - 1] + vals[mid]) / 2.0


def _dt(iso):
    try:
        return datetime.fromisoformat(iso)
    except Exception:
        return None


def _days_between(a, b):
    da, db = _dt(a), _dt(b)
    if not da or not db:
        return None
    return (db - da).total_seconds() / 86400.0


def is_hit(ev):
    """'Este auto me sirve': pasa los filtros duros, entra en el presupuesto y
    puntua como candidato.

    La DISTANCIA se descuenta a proposito. La distancia de un dealer es la misma
    para todos sus coches, asi que si contara aqui, la tasa de un dealer lejano
    seria 0 siempre y no diria nada sobre su inventario. Lo que mide esta tasa
    es "¿este dealer tiene coches de los mios?"; lo lejos que esta se mira
    aparte, en la columna Zona.
    """
    if ev["verdict"] == "EXCLUDED":
        return False
    if ev.get("over_budget"):
        return False
    score = ev["score"] + (25 if ev.get("too_far") else 0)
    return score >= 45


# --------------------------------------------------------------------------
# Tabla de concesionarias
# --------------------------------------------------------------------------

def dealer_table(con, dealers, evaluated, config, now):
    """`evaluated` = [(listing_dict, ev), ...] con TODOS los listings, vivos y
    desaparecidos. La tasa se calcula sobre todo lo observado: cuantos mas
    coches han pasado por el lote, mas fiable es el numero."""
    st = config.get("stats", {})
    z = z_for(st.get("confidence", 0.95))
    strength = float(st.get("prior_strength", 40))
    min_n = int(st.get("min_sample_for_rate", 30))

    seen = defaultdict(int)
    hits = defaultdict(int)
    alive = defaultdict(int)
    alive_hits = defaultdict(int)
    for row, ev in evaluated:
        did = row["dealer_id"]
        seen[did] += 1
        if is_hit(ev):
            hits[did] += 1
        if not row.get("disappeared_at"):
            alive[did] += 1
            if is_hit(ev):
                alive_hits[did] += 1

    total_seen = sum(seen.values())
    total_hits = sum(hits.values())
    # La media global es el punto de partida: "un dealer cualquiera de tu zona".
    prior_mean = (total_hits / total_seen) if total_seen else 0.0

    rows = []
    for d in dealers:
        did = d["id"]
        n, x = seen[did], hits[did]
        lo, hi = wilson_interval(x, n, z)
        adj = shrunk_rate(x, n, prior_mean, strength)

        run = con.execute("SELECT * FROM runs WHERE dealer_id=? ORDER BY started_at DESC LIMIT 1",
                          (did,)).fetchone()
        last_days = None
        if run:
            dd = _days_between(run["started_at"], now.isoformat())
            last_days = int(dd) if dd is not None else None

        rows.append({
            "id": did, "name": d["name"], "cadence_days": d.get("cadence_days"),
            "enabled": d.get("enabled", True), "platform": d.get("platform"),
            "tier": d.get("tier", 2), "note": d.get("note"),
            "inventory": alive[did],
            "candidates": alive_hits[did],
            "observed": n,
            "hits_ever": x,
            "rate": (x / n) if n else None,
            "rate_adj": adj,
            "rate_lo": lo,
            "rate_hi": hi,
            "enough_data": n >= min_n,
            "last_run": run["started_at"] if run else None,
            "last_run_days": last_days,
            "last_ok": bool(run["ok"]) if run else None,
            "requests": run["requests"] if run else 0,
        })

    # Orden: el que mas probable es que te de un coche util, con la evidencia
    # que hay hoy. Un dealer sin una sola corrida no se coloca por delante de
    # otro que si tiene datos: no ha demostrado nada todavia, ni bueno ni malo.
    rows.sort(key=lambda r: (not r["enabled"], r["observed"] == 0,
                             -r["rate_adj"], -r["observed"]))
    for i, r in enumerate(rows):
        r["rank"] = i + 1

    # ¿Se distingue de verdad el primero del segundo? Solo si sus intervalos
    # no se solapan. Si se solapan, decirlo en vez de fingir un ranking.
    active = [r for r in rows if r["enabled"] and r["observed"] > 0]
    verdict = None
    if len(active) >= 2:
        a, b = active[0], active[1]
        separated = a["rate_lo"] > b["rate_hi"]
        verdict = {
            "top": a["name"], "second": b["name"],
            "separated": separated,
            "text": (
                f"{a['name']} destaca de verdad: su peor caso ({a['rate_lo']*100:.1f} %) sigue "
                f"por encima del mejor caso de {b['name']} ({b['rate_hi']*100:.1f} %)."
                if separated else
                f"{a['name']} va primero, pero su margen se solapa con el de {b['name']}: "
                f"con los datos de hoy la diferencia todavia puede ser casualidad. "
                f"Mirad los dos."
            ),
        }

    return rows, {
        "prior_mean": prior_mean,
        "total_seen": total_seen,
        "total_hits": total_hits,
        "confidence": st.get("confidence", 0.95),
        "prior_strength": strength,
        "min_sample": min_n,
        "verdict": verdict,
    }


# --------------------------------------------------------------------------
# Movimientos: comportamiento, no lista de bajas
# --------------------------------------------------------------------------

def _describe(row):
    return " ".join(str(x) for x in (row.get("year"), row.get("make"), row.get("model")) if x)


def rotation(con, dealers, evaluated, now):
    """¿Cuanto aguanta un coche en cada lote antes de irse?

    Solo se cuentan los que VIMOS LLEGAR: si el coche ya estaba en el lote
    cuando empezamos a mirar, no sabemos cuando se publico y contarlo hundiria
    la mediana. (En estadistica esto es censura por la izquierda; la cura barata
    es descartarlos.)
    """
    first_run = {}
    for d in dealers:
        r = con.execute("SELECT MIN(started_at) m FROM runs WHERE dealer_id=? AND ok=1",
                        (d["id"],)).fetchone()
        first_run[d["id"]] = r["m"] if r and r["m"] else None

    by_dealer = defaultdict(lambda: {"gone_hit": [], "gone_all": [], "watching": 0, "watching_hit": 0})
    for row, ev in evaluated:
        did = row["dealer_id"]
        fr = first_run.get(did)
        if not fr:
            continue
        born = _days_between(fr, row["first_seen"])
        if born is None or born < 0.25:      # ya estaba ahi cuando llegamos
            continue
        hit = is_hit(ev)
        if row.get("disappeared_at"):
            days = _days_between(row["first_seen"], row["disappeared_at"])
            if days is not None:
                by_dealer[did]["gone_all"].append(days)
                if hit:
                    by_dealer[did]["gone_hit"].append(days)
        else:
            by_dealer[did]["watching"] += 1
            if hit:
                by_dealer[did]["watching_hit"] += 1

    out = []
    names = {d["id"]: d["name"] for d in dealers}
    for did, b in by_dealer.items():
        n_hit, n_all = len(b["gone_hit"]), len(b["gone_all"])
        med_hit, med_all = _median(b["gone_hit"]), _median(b["gone_all"])
        entry = {
            "dealer_id": did, "name": names.get(did, did),
            "n_gone_hit": n_hit, "n_gone_all": n_all,
            "median_days_hit": round(med_hit, 1) if med_hit is not None else None,
            "median_days_all": round(med_all, 1) if med_all is not None else None,
            "still_here": b["watching"], "still_here_hit": b["watching_hit"],
            "enough": n_all >= 5,
        }
        if n_hit >= 3 and med_hit is not None and med_all is not None:
            if med_hit < med_all * 0.7:
                entry["read"] = ("los autos de TU rango vuelan aqui: duran la mitad que el resto. "
                                 "Si ves uno bueno, llama el mismo dia.")
            elif med_hit > med_all * 1.3:
                entry["read"] = ("los autos de tu rango se quedan parados aqui mas que el resto. "
                                 "Hay margen para esperar una bajada de precio.")
            else:
                entry["read"] = "los autos de tu rango se mueven al mismo ritmo que el resto del lote."
        out.append(entry)
    out.sort(key=lambda e: (e["median_days_hit"] is None, e["median_days_hit"] or 999))
    return out


def relists(con, dealers, now, limit=25):
    """El mismo coche que sale del inventario y vuelve a subir.

    Dos formas de detectarlo, las dos por identidad real del vehiculo:
      · MISMO ANUNCIO   — la ficha desaparecio y reaparecio (evento BACK).
      · REANUNCIADO     — mismo VIN, ficha nueva: lo borraron y lo volvieron a
                          publicar de cero, a veces con otro precio.
    """
    names = {d["id"]: d["name"] for d in dealers}
    out = []

    # 1. mismo VIN, fichas distintas en el mismo dealer
    dupes = con.execute(
        "SELECT dealer_id, vin, COUNT(*) c FROM listings "
        "WHERE vin IS NOT NULL AND TRIM(vin) <> '' "
        "GROUP BY dealer_id, vin HAVING c > 1").fetchall()
    for d in dupes:
        rows = [dict(r) for r in con.execute(
            "SELECT * FROM listings WHERE dealer_id=? AND vin=? ORDER BY first_seen",
            (d["dealer_id"], d["vin"]))]
        prev, cur = rows[-2], rows[-1]
        gap = _days_between(prev["disappeared_at"] or prev["last_seen"], cur["first_seen"])
        out.append({
            "kind": "reanunciado", "dealer_id": d["dealer_id"],
            "dealer": names.get(d["dealer_id"], d["dealer_id"]),
            "what": _describe(cur), "vin": d["vin"],
            "old_price": prev["price"], "new_price": cur["price"],
            "delta": (cur["price"] - prev["price"]) if (cur["price"] and prev["price"]) else None,
            "days_off": round(gap, 1) if gap is not None else None,
            "at": cur["first_seen"], "url": cur["vehicle_url"], "times": len(rows),
        })

    # 2. la misma ficha volvio (evento BACK)
    backs = con.execute(
        "SELECT e.listing_id, e.dealer_id, e.at, l.year, l.make, l.model, l.price, l.vin, l.vehicle_url "
        "FROM events e JOIN listings l ON l.id = e.listing_id "
        "WHERE e.kind='BACK' ORDER BY e.at DESC").fetchall()
    for b in backs:
        gone = con.execute(
            "SELECT at FROM events WHERE listing_id=? AND kind='GONE' AND at < ? "
            "ORDER BY at DESC LIMIT 1", (b["listing_id"], b["at"])).fetchone()
        gap = _days_between(gone["at"], b["at"]) if gone else None
        out.append({
            "kind": "mismo anuncio", "dealer_id": b["dealer_id"],
            "dealer": names.get(b["dealer_id"], b["dealer_id"]),
            "what": _describe(dict(b)), "vin": b["vin"],
            "old_price": None, "new_price": b["price"], "delta": None,
            "days_off": round(gap, 1) if gap is not None else None,
            "at": b["at"], "url": b["vehicle_url"], "times": 2,
        })

    out.sort(key=lambda r: r["at"] or "", reverse=True)
    counts = defaultdict(int)
    for r in out:
        counts[r["dealer_id"]] += 1
    return out[:limit], dict(counts)


def price_swings(con, dealers, now, limit=20):
    """Coches cuyo precio ha SUBIDO y BAJADO. No es lo mismo que una rebaja:
    es un dealer tanteando el mercado, y eso significa que el precio de hoy no
    es sagrado."""
    names = {d["id"]: d["name"] for d in dealers}
    ids = con.execute(
        "SELECT listing_id, COUNT(*) c FROM price_history GROUP BY listing_id HAVING c >= 3").fetchall()
    out = []
    for row in ids:
        series = [r["price"] for r in con.execute(
            "SELECT price FROM price_history WHERE listing_id=? ORDER BY seen_at", (row["listing_id"],))
            if r["price"] is not None]
        if len(series) < 3:
            continue
        ups = sum(1 for a, b in zip(series, series[1:]) if b > a)
        downs = sum(1 for a, b in zip(series, series[1:]) if b < a)
        if not (ups and downs):
            continue
        l = con.execute("SELECT * FROM listings WHERE id=?", (row["listing_id"],)).fetchone()
        if not l:
            continue
        out.append({
            "dealer_id": l["dealer_id"], "dealer": names.get(l["dealer_id"], l["dealer_id"]),
            "what": _describe(dict(l)), "series": series,
            "net": series[-1] - series[0], "moves": ups + downs,
            "url": l["vehicle_url"], "gone": bool(l["disappeared_at"]),
        })
    out.sort(key=lambda r: -r["moves"])
    counts = defaultdict(int)
    for r in out:
        counts[r["dealer_id"]] += 1
    return out[:limit], dict(counts)


def recent_summary(con, dealers, now, days=7):
    """Resumen de los ultimos dias.

    La PRIMERA corrida de cada dealer se salta a proposito: ese dia todo el
    inventario aparece como "nuevo" y son cientos de autos que en realidad
    llevaban ahi meses. Contarlos daria un 'llegaron 539 autos esta semana'
    que no significa nada.
    """
    since = (now - timedelta(days=days)).isoformat()
    got = defaultdict(int)
    seeded = 0
    for d in dealers:
        first = con.execute("SELECT MIN(started_at) m FROM runs WHERE dealer_id=? AND ok=1",
                            (d["id"],)).fetchone()
        if not first or not first["m"]:
            continue
        fr = _dt(first["m"])
        after = (fr + timedelta(hours=1)).isoformat() if fr else first["m"]
        floor = max(since, after)
        for r in con.execute("SELECT kind, COUNT(*) c FROM events WHERE dealer_id=? AND at >= ? "
                             "GROUP BY kind", (d["id"], floor)):
            got[r["kind"]] += r["c"]
        row = con.execute("SELECT COUNT(*) c FROM events WHERE dealer_id=? AND kind='NEW' AND at < ?",
                          (d["id"], after)).fetchone()
        seeded += row["c"] if row else 0
    return {"days": days, "new": got["NEW"], "gone": got["GONE"],
            "drop": got["PRICE_DROP"], "up": got["PRICE_UP"], "back": got["BACK"],
            "seeded": seeded}


def movements(con, dealers, evaluated, config, now):
    rel, rel_counts = relists(con, dealers, now)
    swings, swing_counts = price_swings(con, dealers, now)
    first = con.execute("SELECT MIN(started_at) m FROM runs WHERE ok=1").fetchone()
    observing = _days_between(first["m"], now.isoformat()) if first and first["m"] else None
    return {
        "observing_days": round(observing, 1) if observing is not None else None,
        "summary": recent_summary(con, dealers, now),
        "rotation": rotation(con, dealers, evaluated, now),
        "relists": rel,
        "relist_counts": rel_counts,
        "swings": swings,
        "swing_counts": swing_counts,
    }
