"""API Flask para CarWatch. Solo lee la base de datos; nunca scrapea."""
import json
import os
import sqlite3
import sys
from datetime import datetime, timezone

from flask import Flask, jsonify, send_from_directory

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from carwatch import db, stats, triage  # noqa: E402

DIST = os.path.join(os.path.dirname(os.path.abspath(__file__)), "dist")
app = Flask(__name__, static_folder=DIST, static_url_path="")


def _cfg():
    with open(os.path.join(ROOT, "config.json"), encoding="utf-8") as fh:
        config = json.load(fh)
    with open(os.path.join(ROOT, "risk_rules.json"), encoding="utf-8") as fh:
        rules = json.load(fh)
    with open(os.path.join(ROOT, "dealers.json"), encoding="utf-8") as fh:
        dealers = json.load(fh)
    return config, rules, dealers


def _days_since(iso, now):
    try:
        return int((now - datetime.fromisoformat(iso)).total_seconds() // 86400)
    except Exception:
        return None


@app.route("/")
def index():
    return send_from_directory(DIST, "index.html")


@app.route("/api/data")
def api_data():
    config, rules, dealers = _cfg()
    dmap = {d["id"]: d for d in dealers}
    con = db.connect(os.path.join(ROOT, "data", "carwatch.db"))
    now = datetime.now(timezone.utc)

    # Se evalua TODO el historico una sola vez: los vivos alimentan las tarjetas
    # y los desaparecidos alimentan las estadisticas de cada concesionaria.
    evaluated = []
    for r in con.execute("SELECT * FROM listings"):
        d = dmap.get(r["dealer_id"])
        if not d:
            continue
        item = dict(r)
        evaluated.append((item, triage.evaluate(item, d, config, rules, con, now)))

    vehicles = []
    for item, ev in evaluated:
        if item["disappeared_at"]:
            continue
        d = dmap[item["dealer_id"]]
        hist = [dict(h) for h in con.execute(
            "SELECT seen_at, price FROM price_history WHERE listing_id=? ORDER BY seen_at", (item["id"],))]
        item.update({
            "verdict": ev["verdict"],
            "score": ev["score"],
            "notes": ev["notes"],
            "pros": ev["reasons"],
            "transit_min": ev["transit_min"],
            "transit_home": ev["transit_home"],
            "transit_work": ev["transit_work"],
            "km_ratio": ev["km_ratio"],
            "landed": ev["landed_estimate"],
            "over_budget": ev.get("over_budget"),
            "too_far": ev.get("too_far"),
            "brand_repair": ev.get("brand_repair"),
            "model_severity": ev.get("model_severity"),
            "fuel_effective": triage.infer_fuel(item, item.get("fuel_type")),
            "days_listed": _days_since(item["first_seen"], now),
            "dealer_name": d["name"],
            "price_history": hist,
            "price_drop": (item["price"] - item["first_price"]) if (item["price"] and item["first_price"]) else 0,
        })
        vehicles.append(item)

    dealer_rows, dealer_meta = stats.dealer_table(con, dealers, evaluated, config, now)
    moves = stats.movements(con, dealers, evaluated, config, now)

    return jsonify({
        "generated_at": now.isoformat(timespec="seconds"),
        "filters": config["filters"],
        "anchors": config["anchors"],
        "ui": config.get("ui", {}),
        "vehicles": vehicles,
        "dealers": dealer_rows,
        "dealer_meta": dealer_meta,
        "movements": moves,
    })


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "8080"))
    app.run(host="0.0.0.0", port=port, debug=False)
