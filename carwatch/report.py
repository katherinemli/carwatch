"""Informe en Markdown. Tono deliberadamente tranquilo: esto lista candidatos,
no te dice que compres ni te mete prisa."""
from datetime import datetime, timedelta, timezone

from . import stats, triage

ICON = {"GREEN": "🟢", "YELLOW": "🟡", "RED": "🔴", "EXCLUDED": "⬛"}


def _days(iso, now=None):
    try:
        return int(((now or datetime.now(timezone.utc)) - datetime.fromisoformat(iso)).total_seconds() // 86400)
    except Exception:
        return None


def _money(v):
    return f"${v:,}" if isinstance(v, (int, float)) else "—"


def build(con, dealers, config, rules, since_hours=None):
    now = datetime.now(timezone.utc)
    dmap = {d["id"]: d for d in dealers}
    lines = []
    A = lines.append

    A(f"# 🚗 CarWatch — {now.astimezone().strftime('%Y-%m-%d %H:%M')}")
    A("")
    A("Candidatos para **inspeccionar**, no recomendaciones de compra. "
      "Si algo desaparece, no pasa nada: aparecen coches nuevos cada semana y tu compra es en enero.")
    A("")
    A(f"_Aqui solo salen los que hoy estan a tu alcance: hasta {_money(config['filters']['price_yellow_max'])} "
      f"y a {config['filters']['max_transit_min']} min o menos. Lo caro y lo lejano se sigue guardando y "
      "puntuando con todo su historial; para verlo, sube los sliders en la web._")
    A("")

    # Se evalua todo el historico: los vivos van al informe, y los que ya no
    # figuran alimentan las estadisticas de cada lote.
    scored_all, scored = [], []
    for r in con.execute("SELECT * FROM listings"):
        d = dmap.get(r["dealer_id"])
        if not d:
            continue
        item = dict(r)
        item["_ev"] = triage.evaluate(item, d, config, rules, con, now)
        item["_days"] = _days(r["first_seen"], now)
        item["_dealer"] = d["name"]
        scored_all.append(item)
        if not r["disappeared_at"]:
            scored.append(item)

    for verdict, title, blurb in [
        ("GREEN", "🟢 Destacan — vale la pena tomarselos en serio",
         "Cumplen todo: automatico, en tu presupuesto, kilometraje sensato para su edad y accesibles."),
        ("YELLOW", "🟡 Razonables — merecen la inspeccion de ~$100 antes de decidir",
         "Hay algo que revisar. La inspeccion mecanica es exactamente para esto."),
    ]:
        # El informe es la version corta: solo lo que hoy esta a tu alcance.
        # Lo que se sale de presupuesto o de trayecto se guarda igual y se ve en
        # la web subiendo los sliders; aqui solo seria ruido.
        group = sorted([s for s in scored if s["_ev"]["verdict"] == verdict
                        and not s["_ev"].get("over_budget")
                        and not s["_ev"].get("too_far")],
                       key=lambda s: -s["_ev"]["score"])
        A(f"## {title}")
        A("")
        if not group:
            A("_Nada en esta categoria ahora mismo. Es normal; el historial se sigue acumulando._")
            A("")
            continue
        A(f"_{blurb}_")
        A("")
        for s in group:
            ev = s["_ev"]
            A(f"### {ICON[verdict]} {s['year'] or '?'} {s['make'] or ''} {s['model'] or ''} {s['trim'] or ''} — {_money(s['price'])}")
            A("")
            A(f"- **Dealer:** {s['_dealer']}"
              + (f" · lote: {s['vehicle_location']}" if s["vehicle_location"] else "")
              + f" · ~{ev['transit_min']} min (casa {ev['transit_home']} / trabajo {ev['transit_work']})")
            km_txt = format(s["mileage"], ",") if s["mileage"] is not None else "—"
            if ev["km_ratio"]:
                km_txt += f" ({ev['km_ratio']:.2f}x lo esperado para su edad)"
            A(f"- **Km:** {km_txt}")
            A(f"- **Transmision:** {s['transmission_raw'] or s['transmission']} · **Combustible:** {s['fuel_type'] or '—'}")
            A(f"- **Precio anunciado:** {_money(s['price'])} — "
              f"**con impuestos ≈ {_money(ev['landed_estimate'])}** (sin fees del dealer ni SAAQ)")
            if s["first_price"] and s["price"] and s["first_price"] != s["price"]:
                delta = s["price"] - s["first_price"]
                A(f"- **Precio:** empezo en {_money(s['first_price'])} → {_money(s['price'])} ({delta:+,})")
            if s["_days"] is not None:
                extra = " — lleva tiempo parado, eso suele dar margen para negociar" if s["_days"] >= 45 else ""
                A(f"- **Publicado:** hace {s['_days']} dia(s){extra}")
            if s["stock_number"]:
                A(f"- **Stock:** {s['stock_number']}" + (f" · VIN {s['vin']}" if s["vin"] else ""))
            for note in ev["notes"]:
                A(f"- ⚠️ {note}")
            if s["vehicle_url"]:
                A(f"- [Ver anuncio]({s['vehicle_url']})")
            A("")

    # ---------------- movimientos ----------------
    # Que algo salga del inventario no es accionable: no dice si se vendio, si
    # lo retiraron o si cambio de referencia. Lo que si dice algo es COMO se
    # comporta el lote: si lo tuyo vuela, si re-suben el mismo coche, si el
    # precio va y viene.
    A("## 📈 Movimientos — como se comporta cada lote")
    A("")
    moves = stats.movements(con, dealers, [(s_, s_["_ev"]) for s_ in scored_all], config, now)
    sm = moves["summary"]
    A(f"Ultimos {sm['days']} dias: **{sm['new']}** llegaron · **{sm['gone']}** se fueron · "
      f"**{sm['drop']}** bajaron de precio · **{sm['up']}** subieron."
      + (f" (Sin contar los {sm['seeded']} del primer barrido.)" if sm["seeded"] else ""))
    A("")

    # Solo lo que puede acabar siendo TUYO: un Lexus de $55k que baja $100 no es
    # una noticia, es ruido. El historial completo sigue guardado igual.
    window = (now - timedelta(hours=since_hours or 36)).isoformat()
    ceiling = config["filters"]["price_yellow_max"]
    evs = con.execute(
        "SELECT e.*, l.year, l.make, l.model, l.price, l.vehicle_url "
        "FROM events e JOIN listings l ON l.id = e.listing_id "
        "WHERE e.at >= ? AND e.kind IN ('NEW','PRICE_DROP') AND l.price IS NOT NULL AND l.price <= ? "
        "ORDER BY e.at DESC", (window, ceiling)).fetchall()
    for kind, label in (("PRICE_DROP", "📉 Bajaron de precio"), ("NEW", "🆕 Aparecieron")):
        items = [e for e in evs if e["kind"] == kind]
        if not items:
            continue
        A(f"**{label}** ({len(items)}, dentro de tu tope de {_money(ceiling)})")
        A("")
        for e in items[:25]:
            desc = f"{e['year'] or '?'} {e['make'] or ''} {e['model'] or ''}".strip()
            tail = _money(e["price"]) if kind == "NEW" else (e["detail"] or "")
            A(f"- {desc} — {tail}")
        A("")

    A("**⏱️ ¿Cuanto aguantan en el lote?**")
    A("")
    rot = [r for r in moves["rotation"] if r["n_gone_all"] >= 3]
    if rot:
        A("| Concesionaria | Los tuyos | Todos | Lectura |")
        A("|---|---|---|---|")
        for r in rot:
            mh = f"{r['median_days_hit']} d" if r["median_days_hit"] is not None else "—"
            ma = f"{r['median_days_all']} d" if r["median_days_all"] is not None else "—"
            A(f"| {r['name']} | **{mh}** | {ma} | {r.get('read') or 'aun no dice nada'} |")
    else:
        watching = sum(r["still_here"] for r in moves["rotation"])
        obs = moves["observing_days"]
        A(f"_Llevo {obs} dia(s) mirando y sigo {watching} autos desde que aparecieron. "
          "Para saber cuanto duran hace falta verlos irse: esto se llena solo en dos o tres semanas._")
    A("")

    A("**🔁 El mismo auto, subido otra vez** _(identificado por VIN)_")
    A("")
    if moves["relists"]:
        for r in moves["relists"]:
            bits = [f"{r['what']} — {r['dealer']} ({r['kind']})"]
            if r["old_price"] and r["new_price"]:
                bits.append(f"{_money(r['old_price'])} → {_money(r['new_price'])}")
            elif r["new_price"]:
                bits.append(_money(r["new_price"]))
            if r["days_off"] is not None:
                bits.append(f"fuera {r['days_off']} d")
            A("- " + " · ".join(bits))
    else:
        A("_Ninguno todavia. Aparecera aqui en cuanto un lote borre un anuncio y vuelva a subir el mismo VIN._")
    A("")

    A("**🎢 Precios que suben y bajan**")
    A("")
    if moves["swings"]:
        for r in moves["swings"]:
            serie = " → ".join(_money(p) for p in r["series"])
            A(f"- {r['what']} — {r['dealer']} · {serie}")
    else:
        A("_Nada aun: hace falta ver al menos tres precios distintos del mismo auto._")
    A("")

    # ---------------- estado ----------------
    A("## 🏬 Estado por concesionaria")
    A("")
    drows, dmeta = stats.dealer_table(con, dealers, [(x, x["_ev"]) for x in scored_all], config, now)
    A("| Dealer | Cada | Ultima corrida | En el lote | En tu rango | Vistos | Te sirven |")
    A("|---|---|---|---|---|---|---|")
    for d in drows:
        if d.get("platform") == "blocked":
            last = "— (manual: anti-bot)"
        elif d["last_run_days"] is not None:
            last = ("hoy" if d["last_run_days"] == 0 else f"hace {d['last_run_days']}d") \
                + ("" if d["last_ok"] else " ⚠️ fallo")
        else:
            last = "nunca"
        cad = f"{d['cadence_days']}d" if d.get("cadence_days") else "—"
        if d["observed"] == 0:
            rate = "sin datos"
        else:
            rate = (f"{d['rate_adj']*100:.1f} % "
                    f"({d['rate_lo']*100:.1f}–{d['rate_hi']*100:.1f})")
        A(f"| {d['name']} | {cad} | {last} | {d['inventory']} | **{d['candidates']}** | "
          f"{d['observed']} | {rate} |")
    A("")
    A(f"_**Te sirven** = de cada 100 autos que pasan por ese lote, cuantos entran en tu rango. "
      f"El primer numero es la estimacion ajustada (a quien tiene pocos datos se le hace menos caso "
      f"y se le acerca a la media de todos, que hoy es {dmeta['prior_mean']*100:.1f} %); el parentesis "
      f"es el margen de error real. **Si dos margenes se solapan, la diferencia entre esos dos dealers "
      f"todavia no significa nada.** La distancia no entra en este numero: para eso esta dealers.json._")
    A("")
    if dmeta.get("verdict"):
        A(f"_{dmeta['verdict']['text']}_")
        A("")

    A("---")
    A("")
    A("**Como leer esto**")
    A("")
    A("- 🟢 destaca y merece consideracion seria / inspeccion.")
    A("- 🟡 candidato razonable: la inspeccion de ~$100 es justo el paso siguiente. Puede pasar a 🟢 si sale limpia.")
    A("- 🔴 no vale gastar tiempo ni dinero en inspeccionarlo. Una inspeccion buena normalmente **no** lo sube a 🟢.")
    A("- **Filtros duros** (lo unico que descarta de verdad): usado · automatico · gasolina · con precio publicado · y **marca que no sea cara de reparar**. Es tu primer auto y va sin garantia: las marcas de piezas caras y taller especializado quedan fuera. Se apaga con `filters.exclude_high_repair_brands` en `config.json`.")
    A("- El **precio** y el **trayecto** ya no descartan nada: bajan la nota y nunca dejan un auto en verde, pero se guarda todo el historial. Los sliders de la web solo deciden que ves.")
    A("- Las notas por modelo son la **lista de la compra para el mecanico**, no etiquetas de fiabilidad. Cada modelo tiene sus manias; ahi esta la de este. Editables en `risk_rules.json`.")
    A("- Los minutos de trayecto son **estimaciones tuyas** guardadas en `dealers.json`, no tiempos calculados. Ajustalos cuando conozcas mejor los trayectos.")
    A("- El precio con impuestos es una estimacion (TPS 5% + TVQ 9,975%). **No** incluye fees del dealer, transporte, preparacion, SAAQ ni add-ons.")
    A("")
    return "\n".join(lines)
