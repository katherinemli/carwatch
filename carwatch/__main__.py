"""CLI de CarWatch.

  python3 -m carwatch run        [--force] [--only ID]   corrida respetando cadencias
  python3 -m carwatch report     [--out FICHERO]         informe markdown
  python3 -m carwatch probe      [--only ID]             comprueba robots/plataforma sin scrapear
  python3 -m carwatch status                             que toca y cuando
  python3 -m carwatch history    --key VEHICLE_KEY       historial de precio de un coche
"""
import argparse
import json
import os
import sys
from datetime import datetime

from . import db, report, run as runner
from .fetch import PoliteFetcher

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _load(name):
    with open(os.path.join(ROOT, name), encoding="utf-8") as fh:
        return json.load(fh)


def _save_dealers(dealers):
    with open(os.path.join(ROOT, "dealers.json"), "w", encoding="utf-8") as fh:
        json.dump(dealers, fh, indent=2, ensure_ascii=False)


def _logger(logfile=None):
    handle = open(logfile, "a", encoding="utf-8") if logfile else None

    def log(msg):
        stamp = datetime.now().strftime("%H:%M:%S")
        line = f"[{stamp}] {msg}"
        print(line, flush=True)
        if handle:
            handle.write(line + "\n")
            handle.flush()
    return log


def cmd_run(args):
    config = _load("config.json")
    dealers = _load("dealers.json")
    rules = _load("risk_rules.json")
    con = db.connect(os.path.join(ROOT, "data", "carwatch.db"))
    log = _logger(os.path.join(ROOT, "data", "carwatch.log"))
    cache = os.path.join(ROOT, "data", "cache")

    log(f"=== corrida {datetime.now().isoformat(timespec='seconds')} ===")
    results = []
    for d in dealers:
        if args.only and d["id"] != args.only:
            continue
        res = runner.run_dealer(con, d, config, cache, log, force=args.force)
        if res:
            results.append(res)
            if res.get("blocked"):
                d["platform"] = "blocked"
                d["enabled"] = False
                d["note"] = (d.get("note", "") + " | auto-marcado como bloqueado por anti-bot").strip(" |")

    dealers = runner.autotune(con, dealers, config, log)
    _save_dealers(dealers)

    total_req = sum(r.get("requests", 0) for r in results)
    log(f"=== fin: {len(results)} dealer(s), {total_req} peticiones en total ===")

    if not args.no_report:
        text = report.build(con, dealers, config, rules)
        out = os.path.join(ROOT, "reports", f"carwatch-{datetime.now().strftime('%Y-%m-%d')}.md")
        with open(out, "w", encoding="utf-8") as fh:
            fh.write(text)
        latest = os.path.join(ROOT, "reports", "latest.md")
        with open(latest, "w", encoding="utf-8") as fh:
            fh.write(text)
        log(f"informe: {out}")
    return 0


def cmd_report(args):
    config, dealers, rules = _load("config.json"), _load("dealers.json"), _load("risk_rules.json")
    con = db.connect(os.path.join(ROOT, "data", "carwatch.db"))
    text = report.build(con, dealers, config, rules, since_hours=args.hours)
    if args.out:
        with open(args.out, "w", encoding="utf-8") as fh:
            fh.write(text)
        print(f"escrito en {args.out}")
    else:
        print(text)
    return 0


def cmd_probe(args):
    config, dealers = _load("config.json"), _load("dealers.json")
    log = _logger()
    cache = os.path.join(ROOT, "data", "cache")
    for d in dealers:
        if args.only and d["id"] != args.only:
            continue
        print(f"\n=== {d['name']}  <{d['base']}>")
        f = PoliteFetcher(d["base"], cache, contact=config.get("contact", ""),
                          min_delay=config["politeness"]["min_delay_seconds"],
                          timeout=config["politeness"]["timeout_seconds"], budget=6, log=log)
        try:
            print(f"  robots.txt: {'AUSENTE' if f.robots_missing else 'presente'} · "
                  f"crawl-delay efectivo: {f.effective_delay:.0f}s")
            for path in ([d.get("entry")] if d.get("entry") else []) + ([d.get("sitemap")] if d.get("sitemap") else []):
                allowed = f.allowed(d["base"] + path)
                print(f"  {path}: {'permitido por robots' if allowed else 'PROHIBIDO por robots'}")
            plat = runner.detect_platform(f, log)
            print(f"  plataforma: declarada={d.get('platform')} detectada={plat or 'no concluyente'}")
        except Exception as exc:
            print(f"  ⚠ {type(exc).__name__}: {exc}")
    return 0


def cmd_status(args):
    config, dealers = _load("config.json"), _load("dealers.json")
    con = db.connect(os.path.join(ROOT, "data", "carwatch.db"))
    print(f"{'dealer':<34} {'cada':>5} {'toca?':<28} inventario  en-rango")
    for d in dealers:
        ok, why = runner.due(con, d)
        n = con.execute("SELECT COUNT(*) c FROM listings WHERE dealer_id=? AND disappeared_at IS NULL",
                        (d["id"],)).fetchone()["c"]
        r = con.execute("SELECT COUNT(*) c FROM listings WHERE dealer_id=? AND disappeared_at IS NULL "
                        "AND price<=? AND transmission='AUTOMATIC'",
                        (d["id"], config["filters"]["price_yellow_max"])).fetchone()["c"]
        print(f"{d['name'][:33]:<34} {str(d.get('cadence_days')):>5} {('SI  ' if ok else 'no  ')+why[:24]:<28} {n:>9}  {r:>8}")
    return 0


def cmd_history(args):
    con = db.connect(os.path.join(ROOT, "data", "carwatch.db"))
    row = con.execute("SELECT * FROM listings WHERE vehicle_key=? OR stock_number=? OR vin=?",
                      (args.key, args.key, args.key)).fetchone()
    if not row:
        print("no encontrado")
        return 1
    print(f"{row['year']} {row['make']} {row['model']} — {row['dealer_id']}")
    print(f"visto por primera vez: {row['first_seen']}  ·  ultima vez: {row['last_seen']}")
    if row["disappeared_at"]:
        print(f"ya no figura desde: {row['disappeared_at']}")
    for h in con.execute("SELECT * FROM price_history WHERE listing_id=? ORDER BY seen_at", (row["id"],)):
        print(f"  {h['seen_at']}  ${h['price']:,}")
    return 0


def main(argv=None):
    p = argparse.ArgumentParser(prog="carwatch", description="Rastreador educado de inventario usado")
    sub = p.add_subparsers(dest="cmd", required=True)

    r = sub.add_parser("run", help="corrida respetando cadencias")
    r.add_argument("--force", action="store_true", help="ignora la cadencia y corre igual")
    r.add_argument("--only", help="solo este dealer (id)")
    r.add_argument("--no-report", action="store_true")
    r.set_defaults(func=cmd_run)

    rep = sub.add_parser("report", help="genera el informe markdown")
    rep.add_argument("--out")
    rep.add_argument("--hours", type=int, default=36, help="ventana de 'movimientos recientes'")
    rep.set_defaults(func=cmd_report)

    pr = sub.add_parser("probe", help="comprueba robots/plataforma sin scrapear inventario")
    pr.add_argument("--only")
    pr.set_defaults(func=cmd_probe)

    st = sub.add_parser("status", help="que dealer toca y cuando")
    st.set_defaults(func=cmd_status)

    hi = sub.add_parser("history", help="historial de precio de un vehiculo")
    hi.add_argument("--key", required=True, help="vehicle_key, stock o VIN")
    hi.set_defaults(func=cmd_history)

    args = p.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
