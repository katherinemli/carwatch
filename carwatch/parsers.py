"""Extraccion de vehiculos. Dos plataformas reales detectadas en los dealers de Katherine."""
import base64
import html as htmlmod
import json
import re

# --------------------------------------------------------------------------
# utilidades
# --------------------------------------------------------------------------

def _txt(s):
    if s is None:
        return None
    s = re.sub(r"<[^>]+>", " ", s)
    s = htmlmod.unescape(s)
    s = re.sub(r"\s+", " ", s).strip()
    return s or None


def _int(s):
    if s is None:
        return None
    m = re.findall(r"\d+", str(s).replace(",", "").replace(" ", " ").replace(" ", ""))
    return int("".join(m)) if m else None


FEE_KEYWORDS = [
    "corrosion", "antirouille", "anti-rouille", "rustproof", "paint protection",
    "protection de la peinture", "extended warranty", "garantie prolongee",
    "garantie prolongée", "tire and rim", "pneus et jantes", "roues et pneus",
    "admin fee", "frais d'administration", "frais de preparation",
    "frais de préparation", "preparation fee", "documentation fee",
    "frais de transport", "transport et preparation", "dealer bonus",
    "financing rate", "etching", "gravure", "nitrogen", "azote",
]


def find_fee_flags(text):
    if not text:
        return []
    low = text.lower()
    return sorted({k for k in FEE_KEYWORDS if k in low})


def _decode_tooltips(chunk):
    """Los tooltips de D2C vienen en base64. Ahi viven los descargos de precio."""
    out = []
    for raw in re.findall(r"data-tooltip=['\"]([A-Za-z0-9+/=]{16,})['\"]", chunk):
        try:
            dec = base64.b64decode(raw + "===").decode("utf-8", errors="replace")
            t = _txt(htmlmod.unescape(dec))
            if t:
                out.append(t)
        except Exception:
            continue
    return out


AUTO_RE = re.compile(r"\b(auto|automat|cvt|a/t|tiptronic|dsg|pdk|steptronic|xtronic)", re.I)
MANUAL_RE = re.compile(r"\b(manual|manuelle|man\.|\d\s*-?\s*speed\s+manual)", re.I)


def normalize_transmission(raw):
    if not raw:
        return None
    if MANUAL_RE.search(raw) and not AUTO_RE.search(raw):
        return "MANUAL"
    if AUTO_RE.search(raw):
        return "AUTOMATIC"
    return raw.strip().upper()[:40]


def normalize_fuel(raw):
    if not raw:
        return None
    low = raw.lower()
    for key, val in [("electric", "Electric"), ("électri", "Electric"), ("hybrid", "Hybrid"),
                     ("hybride", "Hybrid"), ("diesel", "Diesel"), ("gas", "Gasoline"),
                     ("essence", "Gasoline"), ("petrol", "Gasoline")]:
        if key in low:
            return val
    return raw.strip()[:30]


# --------------------------------------------------------------------------
# D2C Media  (Mazda Gabriel, Excel Honda)
# --------------------------------------------------------------------------

def d2c_seo_links(page):
    """Paginas por marca+modelo, sin query string. Asi recorremos TODO el inventario
    sin tocar la paginacion JS ni parametros prohibidos.

    Algunos sitios D2C son solo en frances y usan /occasion/ en vez de /used/."""
    return sorted(set(re.findall(
        r'href="(/(?:used|occasion)/[A-Za-z0-9_]+-[A-Za-z0-9_]+\.html)"', page)))


def parse_d2c(page, base):
    cards = []
    parts = page.split('<li class="carBoxWrapper"')
    for chunk in parts[1:]:
        chunk = chunk[:20000]
        vd = re.search(r'<input name="vehicledata"[^>]*>', chunk)
        attrs = {}
        if vd:
            for k, v in re.findall(r'data-([a-z\-]+)="([^"]*)"', vd.group(0)):
                attrs[k] = htmlmod.unescape(v).strip()

        carid = attrs.get("carid") or (re.search(r'data-carid="(\d+)"', chunk) or [None, None])[1]
        if not carid:
            continue

        price = None
        pm = re.search(r"class='dollarsigned[^']*'>([0-9,\. ]+)</span>", chunk)
        if pm:
            price = _int(pm.group(1))

        km = None
        kmm = re.search(r"class='s-km'>([^<]+)</span>", chunk)
        if kmm:
            km = _int(kmm.group(1))

        detail = {}
        for label, value in re.findall(
                r"<span>\s*([A-Za-zÀ-ÿ# ]{3,25}?)\s*:?\s*</span>\s*<span class=\"-ph --s\">\s*([^<]{1,60}?)\s*</span>", chunk):
            detail[label.strip().rstrip(":").lower()] = htmlmod.unescape(value).strip()

        banner = None
        bm = re.search(r"(?s)<div class='carBannerWrapper'>.*?<span>([^<]{1,40})</span>", chunk)
        if bm:
            banner = _txt(bm.group(1))

        loc_name, loc_addr = None, None
        lm = re.search(r'(?s)<div class="vehicleLocation.*?<span class="-bold --fs3">([^<]+)</span>(.*?)</div>', chunk)
        if lm:
            loc_name = _txt(lm.group(1))
            am = re.search(r'uvdp-located-address[^>]*>([^<]+)<', lm.group(2))
            loc_addr = _txt(am.group(1)) if am else None

        um = re.search(r'href="(/(?:used|demos|occasion)/[^"]*-id' + re.escape(carid) + r'\.html)"', chunk)
        url = base + um.group(1) if um else None
        is_demo = bool(um and "/demos/" in um.group(1))

        fee_text = " | ".join(_decode_tooltips(chunk))
        small = " ".join(_txt(x) or "" for x in re.findall(r'class="p-small-msg"[^>]*>([^<]*)<', chunk))

        cond = (attrs.get("condition") or "").upper()
        status = "IN_STOCK"
        if banner and re.search(r"(?i)sold|vendu", banner):
            status = "SOLD"
        elif banner and re.search(r"(?i)transit|chemin", banner):
            status = "IN_TRANSIT"
        elif is_demo or banner and re.search(r"(?i)demo", banner):
            status = "DEMO"
        if cond == "NEW":
            status = "NEW"

        cards.append({
            "vehicle_key": f"d2c:{carid}",
            "stock_number": attrs.get("stock-number"),
            "vin": attrs.get("vin"),
            "make": attrs.get("make"),
            "model": attrs.get("model"),
            "year": _int(attrs.get("year")),
            "trim": attrs.get("trim") or detail.get("category"),
            "price": price,
            "mileage": km,
            "transmission": normalize_transmission(detail.get("transmission")),
            "transmission_raw": detail.get("transmission"),
            "fuel_type": normalize_fuel(detail.get("fuel")),
            "engine": detail.get("engine"),
            "body_style": detail.get("category"),
            "exterior_color": detail.get("exterior colour") or detail.get("exterior color"),
            "condition": "USED" if cond in ("USED", "") else cond,
            "status": status,
            "vehicle_url": url,
            "vehicle_location": loc_name,
            "vehicle_address": loc_addr,
            "fee_notes": (fee_text + (" | " + small if small.strip() else "")).strip(" |") or None,
            "fee_flags": ",".join(find_fee_flags(fee_text + " " + small)) or None,
            "price_note": _txt(re.search(r"<span class='p-msg'>([^<]+)</span>", chunk).group(1)) if re.search(r"<span class='p-msg'>([^<]+)</span>", chunk) else None,
        })
    return cards


# --------------------------------------------------------------------------
# Sm360 / Showroom360  (Spinelli, Mont-Royal Chevrolet, Hyundai, Silver Star)
# --------------------------------------------------------------------------

def sm360_sitemap_urls(xml, marker="used-inventory"):
    locs = re.findall(r"<loc>\s*([^<]+?)\s*</loc>", xml)
    return sorted({u for u in locs if marker in u and re.search(r"-id\d+$", u)})


def parse_sm360_vdp(page, url):
    car = None
    for blob in re.findall(r'(?s)<script type="application/ld\+json">(.*?)</script>', page):
        try:
            data = json.loads(blob.strip())
        except Exception:
            continue
        for cand in (data if isinstance(data, list) else [data]):
            if isinstance(cand, dict) and cand.get("@type") in ("Car", "Vehicle", "Motorcycle"):
                car = cand
                break
        if car:
            break
    if not car:
        return None

    offers = car.get("offers") or {}
    if isinstance(offers, list):
        offers = offers[0] if offers else {}
    seller = offers.get("seller") or {}
    addr = seller.get("address") or {}

    odo = car.get("mileageFromOdometer") or {}
    mileage = _int(odo.get("value") if isinstance(odo, dict) else odo)

    engines = car.get("vehicleEngine") or []
    if isinstance(engines, dict):
        engines = [engines]
    fuel = engines[0].get("fuelType") if engines and isinstance(engines[0], dict) else None
    engine_type = engines[0].get("engineType") if engines and isinstance(engines[0], dict) else None

    avail = str(offers.get("availability") or "")
    status = "IN_STOCK" if "InStock" in avail else ("SOLD" if "SoldOut" in avail or "OutOfStock" in avail else avail.split("/")[-1].upper() or "UNKNOWN")

    vid = re.search(r"-id(\d+)$", url)
    body_text = _txt(page[:400000]) or ""

    address_str = ", ".join(x for x in [addr.get("streetAddress"), addr.get("addressLocality"), addr.get("postalCode")] if x)

    return {
        "vehicle_key": f"sm360:{vid.group(1) if vid else url}",
        "stock_number": (car.get("sku") if car.get("sku") not in ("n/a", None) else None) or (car.get("mpn") if car.get("mpn") not in ("n/a", None) else None),
        "vin": car.get("vehicleIdentificationNumber"),
        "make": car.get("brand") if isinstance(car.get("brand"), str) else (car.get("brand") or {}).get("name"),
        "model": car.get("model"),
        "year": _int(car.get("modelDate") or car.get("vehicleModelDate") or car.get("productionDate")),
        "trim": car.get("vehicleConfiguration"),
        "price": _int(offers.get("price")),
        "mileage": mileage,
        "transmission": normalize_transmission(car.get("vehicleTransmission")),
        "transmission_raw": car.get("vehicleTransmission"),
        "fuel_type": normalize_fuel(fuel),
        "engine": engine_type,
        "body_style": car.get("bodyType"),
        "exterior_color": car.get("color"),
        "condition": "USED" if "Used" in str(car.get("itemCondition")) else "NEW",
        "status": status,
        "vehicle_url": offers.get("url") or url,
        "vehicle_location": seller.get("name"),
        "vehicle_address": address_str or None,
        "fee_notes": None,
        "fee_flags": ",".join(find_fee_flags(body_text)) or None,
        "price_note": None,
    }
