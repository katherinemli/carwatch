"""Persistencia. Lo importante no es la foto de hoy, es la serie temporal."""
import os
import sqlite3
from datetime import datetime, timezone

FIELDS = ["stock_number", "vin", "make", "model", "year", "trim", "price", "mileage",
          "transmission", "transmission_raw", "fuel_type", "engine", "body_style",
          "exterior_color", "condition", "status", "vehicle_url", "vehicle_location",
          "vehicle_address", "fee_notes", "fee_flags", "price_note"]

SCHEMA = """
CREATE TABLE IF NOT EXISTS listings (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  dealer_id TEXT NOT NULL,
  vehicle_key TEXT NOT NULL,
  stock_number TEXT, vin TEXT, make TEXT, model TEXT, year INTEGER, trim TEXT,
  price INTEGER, mileage INTEGER, transmission TEXT, transmission_raw TEXT,
  fuel_type TEXT, engine TEXT, body_style TEXT, exterior_color TEXT,
  condition TEXT, status TEXT, vehicle_url TEXT,
  vehicle_location TEXT, vehicle_address TEXT,
  fee_notes TEXT, fee_flags TEXT, price_note TEXT,
  first_seen TEXT NOT NULL, last_seen TEXT NOT NULL,
  first_price INTEGER, min_price INTEGER, max_price INTEGER,
  disappeared_at TEXT,
  UNIQUE(dealer_id, vehicle_key)
);
CREATE TABLE IF NOT EXISTS price_history (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  listing_id INTEGER NOT NULL, seen_at TEXT NOT NULL, price INTEGER,
  FOREIGN KEY(listing_id) REFERENCES listings(id)
);
CREATE TABLE IF NOT EXISTS events (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  listing_id INTEGER, dealer_id TEXT, kind TEXT NOT NULL,
  at TEXT NOT NULL, detail TEXT
);
CREATE TABLE IF NOT EXISTS runs (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  dealer_id TEXT NOT NULL, started_at TEXT NOT NULL, finished_at TEXT,
  ok INTEGER DEFAULT 0, n_seen INTEGER DEFAULT 0, requests INTEGER DEFAULT 0,
  unchanged INTEGER DEFAULT 0, note TEXT
);
CREATE INDEX IF NOT EXISTS idx_listings_dealer ON listings(dealer_id);
CREATE INDEX IF NOT EXISTS idx_listings_price ON listings(price);
CREATE INDEX IF NOT EXISTS idx_events_at ON events(at);
CREATE INDEX IF NOT EXISTS idx_runs_dealer ON runs(dealer_id, started_at);
"""


def now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def connect(path):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    con = sqlite3.connect(path)
    con.row_factory = sqlite3.Row
    con.executescript(SCHEMA)
    return con


def start_run(con, dealer_id):
    cur = con.execute("INSERT INTO runs(dealer_id, started_at) VALUES (?,?)", (dealer_id, now()))
    con.commit()
    return cur.lastrowid, now()


def finish_run(con, run_id, ok, n_seen, requests, unchanged=0, note=None):
    con.execute("UPDATE runs SET finished_at=?, ok=?, n_seen=?, requests=?, unchanged=?, note=? WHERE id=?",
                (now(), 1 if ok else 0, n_seen, requests, unchanged, note, run_id))
    con.commit()


def _event(con, listing_id, dealer_id, kind, detail=None):
    con.execute("INSERT INTO events(listing_id, dealer_id, kind, at, detail) VALUES (?,?,?,?,?)",
                (listing_id, dealer_id, kind, now(), detail))


def upsert(con, dealer_id, v):
    """Devuelve (listing_id, kind) donde kind es None|NEW|PRICE_DROP|PRICE_UP|BACK."""
    ts = now()
    row = con.execute("SELECT * FROM listings WHERE dealer_id=? AND vehicle_key=?",
                      (dealer_id, v["vehicle_key"])).fetchone()
    kind = None
    if row is None:
        cols = ", ".join(FIELDS)
        marks = ", ".join("?" for _ in FIELDS)
        cur = con.execute(
            f"INSERT INTO listings(dealer_id, vehicle_key, {cols}, first_seen, last_seen, first_price, min_price, max_price) "
            f"VALUES (?,?,{marks},?,?,?,?,?)",
            [dealer_id, v["vehicle_key"]] + [v.get(f) for f in FIELDS] + [ts, ts, v.get("price"), v.get("price"), v.get("price")])
        lid = cur.lastrowid
        kind = "NEW"
        _event(con, lid, dealer_id, "NEW", f"{v.get('year')} {v.get('make')} {v.get('model')} @ {v.get('price')}")
        if v.get("price") is not None:
            con.execute("INSERT INTO price_history(listing_id, seen_at, price) VALUES (?,?,?)", (lid, ts, v["price"]))
    else:
        lid = row["id"]
        old_price = row["price"]
        new_price = v.get("price")
        sets = ", ".join(f"{f}=?" for f in FIELDS)
        con.execute(f"UPDATE listings SET {sets}, last_seen=? WHERE id=?",
                    [v.get(f) for f in FIELDS] + [ts, lid])
        if row["disappeared_at"]:
            con.execute("UPDATE listings SET disappeared_at=NULL WHERE id=?", (lid,))
            kind = "BACK"
            _event(con, lid, dealer_id, "BACK", "volvio a aparecer en el inventario")
        if new_price is not None and old_price is not None and new_price != old_price:
            con.execute("INSERT INTO price_history(listing_id, seen_at, price) VALUES (?,?,?)", (lid, ts, new_price))
            delta = new_price - old_price
            kind = "PRICE_DROP" if delta < 0 else "PRICE_UP"
            _event(con, lid, dealer_id, kind, f"{old_price} -> {new_price} ({delta:+d})")
            con.execute("UPDATE listings SET min_price=MIN(COALESCE(min_price,?),?), max_price=MAX(COALESCE(max_price,?),?) WHERE id=?",
                        (new_price, new_price, new_price, new_price, lid))
        elif new_price is not None and old_price is None:
            con.execute("INSERT INTO price_history(listing_id, seen_at, price) VALUES (?,?,?)", (lid, ts, new_price))
            con.execute("UPDATE listings SET first_price=COALESCE(first_price,?), min_price=?, max_price=? WHERE id=?",
                        (new_price, new_price, new_price, lid))
    con.commit()
    return lid, kind


def mark_disappeared(con, dealer_id, run_started_at, seen_count):
    """Solo se marca 'desaparecido' si la corrida fue completa y trajo datos.
    Asi un fallo de red no borra medio inventario."""
    if seen_count <= 0:
        return []
    rows = con.execute(
        "SELECT id, year, make, model, price FROM listings "
        "WHERE dealer_id=? AND disappeared_at IS NULL AND last_seen < ?",
        (dealer_id, run_started_at)).fetchall()
    for r in rows:
        con.execute("UPDATE listings SET disappeared_at=? WHERE id=?", (now(), r["id"]))
        _event(con, r["id"], dealer_id, "GONE",
               f"{r['year']} {r['make']} {r['model']} @ {r['price']} — ya no figura en el inventario")
    con.commit()
    return rows


def touch(con, dealer_id, vehicle_keys):
    """Marca 'sigue en el inventario' sin re-descargar la ficha completa.
    Sin esto, un coche que existe pero que no tocamos esta corrida se marcaria
    como desaparecido por error."""
    if not vehicle_keys:
        return 0
    ts = now()
    n = 0
    for key in vehicle_keys:
        cur = con.execute("UPDATE listings SET last_seen=? WHERE dealer_id=? AND vehicle_key=?",
                          (ts, dealer_id, key))
        n += cur.rowcount
    con.commit()
    return n


def known_keys(con, dealer_id):
    return {r["vehicle_key"]: r for r in
            con.execute("SELECT vehicle_key, price, last_seen FROM listings WHERE dealer_id=?", (dealer_id,))}
