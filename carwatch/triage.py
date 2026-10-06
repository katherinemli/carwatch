"""Triage 🟢/🟡/🔴 con los criterios de Katherine.

Objetivo declarado: identificar CANDIDATOS para inspeccionar, no empujar a comprar.

Dos ideas que mandan sobre todo lo demas:

1. Es un PRIMER auto, barato y sin garantia. Lo que arruina esa compra no es que
   el coche falle -- todos fallan -- sino que CADA fallo cueste una fortuna. Por
   eso las marcas de piezas caras / taller especializado son un descarte duro,
   no una nota al pie.
2. El precio y el trayecto NO son filtros duros. Todo se guarda y se puntua; lo
   que decide que se VE es el filtro de la web. La informacion no se tira nunca.
"""
import json
import os
import re
from datetime import datetime, timezone

GREEN, YELLOW, RED, EXCLUDED = "GREEN", "YELLOW", "RED", "EXCLUDED"


def _load(path, default):
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except Exception:
        return default


EV_HINTS = ("leaf", "bolt", "tesla", "model 3", "model s", "model y", "i3", "e-golf",
            "ioniq 5", "ioniq 6", "kona electric", "niro ev", "soul ev", "id.4", "mach-e")


def infer_fuel(listing, current):
    """El tooltip de D2C a veces trae la etiqueta en vez del valor. Se completa
    con el motor y el nombre del modelo antes de puntuar."""
    engine = (listing.get("engine") or "").lower()
    model = (listing.get("model") or "").lower()
    if "electric" in engine or any(h in model for h in EV_HINTS):
        return "Electric"
    if "diesel" in engine:
        return "Diesel"
    if "hybrid" in engine:
        return "Hybrid"
    import re as _re
    if current and current.strip().lower() in ("fuel", "carburant", "n/a", "unknown", "-"):
        # D2C publica literalmente "Fuel: Fuel" cuando el campo va vacio.
        # Un motor con cilindrada y cilindros es combustion interna; sin
        # indicios de diesel/hibrido/electrico, es gasolina.
        if (_re.search(r"\d[.,]\d\s*l\b", engine, _re.I)
                or _re.search(r"\b[vlih]\d\b", engine, _re.I)
                or "cyl" in engine):
            return "Gasoline"
        return None
    return current


# --------------------------------------------------------------------------
# Marca: coste y facilidad de REPARAR, no "fiabilidad"
# --------------------------------------------------------------------------

# Compatibilidad con el risk_rules.json viejo (brand_risk low/medium/high).
_LEGACY_TIERS = {"low": "facil", "medium": "normal", "high": "caro"}


def _brand_table(rules):
    table = rules.get("brand_repair")
    if table:
        return table
    legacy = rules.get("brand_risk") or {}
    return {_LEGACY_TIERS[k]: v for k, v in legacy.items() if k in _LEGACY_TIERS}


def brand_repair(rules, make):
    """'facil' | 'normal' | 'caro'. Sin datos, se asume 'normal'."""
    if not make:
        return "normal"
    m = make.strip().lower()
    table = _brand_table(rules)
    for level in ("facil", "normal", "caro"):
        for b in table.get(level, []):
            if b.lower() == m:
                return level
    return "normal"


# Alias historico: report.py y cualquier script viejo siguen funcionando.
def brand_tier(rules, make):
    inverse = {"facil": "low", "normal": "medium", "caro": "high"}
    return inverse[brand_repair(rules, make)]


# --------------------------------------------------------------------------
# Modelo: QUE revisar, con que peso. Nunca una etiqueta de "poco fiable".
# --------------------------------------------------------------------------

def model_check(rules, model):
    """Devuelve {'severidad': ..., 'revisar': ...} o None.

    Se busca la coincidencia mas LARGA para que 'Mazda3' gane a 'Mazda' y
    'Grand Caravan' gane a 'Caravan'.
    """
    if not model:
        return None
    low = model.lower()
    checks = rules.get("model_checks")
    if checks:
        best = None
        for key, val in checks.items():
            if key.startswith("_") or not isinstance(val, dict):
                continue
            if key.lower() in low and (best is None or len(key) > len(best[0])):
                best = (key, val)
        if best:
            return {"severidad": best[1].get("severidad", "media"),
                    "revisar": best[1].get("revisar", "")}
        return None
    # formato viejo: {"Journey": "texto"}
    for key, note in (rules.get("model_notes") or {}).items():
        if key.startswith("_"):
            continue
        if key.lower() in low:
            return {"severidad": "media", "revisar": note}
    return None


def model_note(rules, model):
    """Alias historico: solo el texto."""
    c = model_check(rules, model)
    return c["revisar"] if c else None


def transit_for(dealer, vehicle_location):
    lots = dealer.get("lots") or {}
    chosen = None
    if vehicle_location:
        for name, vals in lots.items():
            if name == "_default":
                continue
            if name.lower() in vehicle_location.lower() or vehicle_location.lower() in name.lower():
                chosen = vals
                break
    if chosen is None:
        chosen = lots.get("_default") or {"transit_home_min": 45, "transit_work_min": 45}
    home = chosen.get("transit_home_min", 45)
    work = chosen.get("transit_work_min", 45)
    return min(home, work), home, work


def peer_median_price(con, make, model, year, span=2):
    if not (make and model and year):
        return None
    rows = con.execute(
        "SELECT price FROM listings WHERE make=? AND model=? AND year BETWEEN ? AND ? "
        "AND price IS NOT NULL AND price > 0",
        (make, model, year - span, year + span)).fetchall()
    prices = sorted(r["price"] for r in rows)
    if len(prices) < 4:
        return None
    mid = len(prices) // 2
    return prices[mid] if len(prices) % 2 else (prices[mid - 1] + prices[mid]) / 2


def evaluate(listing, dealer, config, rules, con=None, today=None):
    f = config["filters"]
    today = today or datetime.now(timezone.utc)
    year_now = today.year

    price = listing.get("price")
    km = listing.get("mileage")
    year = listing.get("year")
    trans = listing.get("transmission")
    fuel = infer_fuel(listing, listing.get("fuel_type"))
    status = (listing.get("status") or "").upper()
    cond = (listing.get("condition") or "").upper()

    hard = []      # motivos de exclusion
    notes = []     # avisos para la inspeccion
    plus = []      # razones a favor

    transit_min, t_home, t_work = transit_for(dealer, listing.get("vehicle_location"))
    repair = brand_repair(rules, listing.get("make"))
    landed = None
    if price is not None:
        t = config["taxes"]
        landed = round(price * (1 + t["gst"] + t["qst"]))

    base = {"transit_min": transit_min, "transit_home": t_home, "transit_work": t_work,
            "brand_repair": repair, "brand_tier": brand_tier(rules, listing.get("make")),
            "landed_estimate": landed}

    # ---------------- filtros duros ----------------
    # Solo lo INTRINSECO al coche: lo que ninguna negociacion ni ningun slider
    # cambia. Precio y trayecto ya NO viven aqui.
    if cond and cond != "USED":
        hard.append(f"no es usado ({cond})")
    if status in [s.upper() for s in f["exclude_status"]]:
        hard.append(f"estado excluido: {status}")
    if trans != "AUTOMATIC":
        hard.append(f"transmision {trans or 'desconocida'} (necesitas automatica)")
    if f.get("require_gasoline"):
        if fuel and any(x.lower() in fuel.lower() for x in f.get("fuel_excluded", [])):
            hard.append(f"{fuel}: solo quieres gasolina")
        elif not fuel:
            hard.append("combustible no confirmado (solo quieres gasolina)")
    if price is None:
        hard.append("sin precio publicado")
    if f.get("exclude_high_repair_brands", True) and repair == "caro":
        hard.append(f"{listing.get('make')}: piezas caras y taller especializado. "
                    "Para un primer auto sin garantia, una averia normal se vuelve una factura de miles")

    if hard:
        return dict(base, verdict=EXCLUDED, score=0, reasons=hard, notes=notes,
                    km_ratio=None, over_budget=None, too_far=transit_min > f["max_transit_min"],
                    model_severity=None, model_check=None)

    # ---------------- puntuacion ----------------
    score = 100
    age = max(year_now - year, 0) if year else None

    # kilometraje relativo a la edad
    km_ratio = None
    if km is not None and age is not None and age > 0:
        expected = age * f["km_per_year_expected"]
        km_ratio = km / expected if expected else None
    if km is not None and km > f["km_absolute_max"]:
        score -= 45
        notes.append(f"{km:,} km es muchisimo; el desgaste ya no depende del precio")
    elif km_ratio is not None:
        if km_ratio <= 0.85:
            score += 10
            plus.append(f"kilometraje bajo para su edad ({km_ratio:.2f}x lo esperado)")
        elif km_ratio <= f["km_ratio_green_max"]:
            plus.append(f"kilometraje normal para su edad ({km_ratio:.2f}x)")
        elif km_ratio <= f["km_ratio_yellow_max"]:
            score -= 15
            notes.append(f"kilometraje alto para su edad ({km_ratio:.2f}x lo esperado)")
        else:
            score -= 30
            notes.append(f"kilometraje muy alto para su edad ({km_ratio:.2f}x lo esperado)")

    # edad: no penalizamos por viejo si cumple lo demas, solo un ajuste suave
    if age is not None:
        if age <= 10:
            plus.append(f"{age} anos")
        elif age <= f["age_green_max"]:
            score -= 5
        else:
            score -= 12
            notes.append(f"{age} anos: piezas y oxido son el riesgo real, no el motor")

    # marca: coste de reparar
    if repair == "facil":
        score += 8
        plus.append("piezas baratas y lo arregla cualquier taller")
    elif repair == "normal":
        plus.append("piezas y taller de precio corriente")

    # modelo: la lista de la compra para el mecanico
    check = model_check(rules, listing.get("model"))
    severity = check["severidad"] if check else None
    if check:
        if severity == "alta":
            score -= 14
        elif severity == "media":
            score -= 5
        notes.append(check["revisar"])

    # combustible
    fuel_penalized = False
    if fuel and any(p.lower() in fuel.lower() for p in f["fuel_preferred"]):
        score += 5
        plus.append("gasolina")
    elif fuel and any(p.lower() in fuel.lower() for p in f["fuel_penalized"]):
        score -= 20
        fuel_penalized = True
        notes.append(f"{fuel}: para un primer auto barato anade riesgo caro (bateria/sistema)")

    # precio: banda, no muro
    over_budget = price > f["price_yellow_max"]
    if price <= f["price_green_max"]:
        plus.append(f"${price:,} dentro de tu objetivo")
    elif not over_budget:
        score -= 15
        notes.append(f"${price:,} esta en tu banda amarilla (sobre ${f['price_green_max']:,})")
        if f.get("price_yellow_needs_proximity") and transit_min > 30:
            score -= 10
            notes.append("banda amarilla Y lejos: solo vale si es claramente mejor")
    else:
        # El castigo crece con lo lejos que esta del tope: $12.500 es "casi" y
        # $50.000 es otro planeta. Un castigo fijo los dejaba a los dos en
        # amarillo, que es justo lo que no queremos.
        over = price / f["price_yellow_max"]
        score -= min(80, round(30 + 45 * (over - 1)))
        notes.append(f"${price:,} pasa tu tope de ${f['price_yellow_max']:,}. "
                     "Se guarda por si baja, pero hoy no entra en tu presupuesto")

    # cercania: tambien banda, no muro
    too_far = transit_min > f["max_transit_min"]
    if too_far:
        score -= min(45, round(18 + 0.5 * (transit_min - f["max_transit_min"])))
        notes.append(f"~{transit_min} min de trayecto, pasa tu tope de {f['max_transit_min']} min. "
                     "Se guarda el historial; sube el slider de trayecto si quieres verlo")
    elif transit_min <= 20:
        score += 10
        plus.append(f"~{transit_min} min de casa o trabajo")
    elif transit_min <= 30:
        score += 5
        plus.append(f"~{transit_min} min")

    # "un precio extremadamente bajo no es automaticamente buena oferta"
    suspicious = False
    peer = peer_median_price(con, listing.get("make"), listing.get("model"), year) if con is not None else None
    if peer and price < 0.5 * peer:
        suspicious = True
        notes.append(f"precio muy por debajo de comparables (mediana ~${int(peer):,}): averigua POR QUE antes de ilusionarte")
    if price <= 3500 and km is not None and km >= 200000:
        suspicious = True
        notes.append("muy barato y muy rodado a la vez: normalmente el precio refleja algo real")
    if suspicious:
        score -= 20

    # fees / add-ons
    if listing.get("fee_flags"):
        notes.append("el anuncio menciona extras/fees: " + listing["fee_flags"].replace(",", ", "))

    # ---------------- veredicto ----------------
    # Verde = "esto destaca de verdad". Cualquier cosa que obligue a mirar dos
    # veces (fuera de presupuesto, lejos, punto debil caro conocido) lo baja a
    # amarillo: sigue siendo candidato, pero con deberes.
    blocks_green = (over_budget or too_far or suspicious or fuel_penalized
                    or severity == "alta" or repair == "caro"
                    or price > f["price_green_max"]
                    or (km_ratio is not None and km_ratio > f["km_ratio_green_max"]))
    if score >= 70 and not blocks_green:
        verdict = GREEN
    elif score >= 45:
        verdict = YELLOW
    else:
        verdict = RED

    return dict(base, verdict=verdict, score=score, reasons=plus, notes=notes,
                km_ratio=km_ratio, over_budget=over_budget, too_far=too_far,
                model_severity=severity, model_check=check["revisar"] if check else None)
