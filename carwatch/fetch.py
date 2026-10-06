"""Fetcher educado: robots.txt, crawl-delay, cache condicional, presupuesto de peticiones.

Reglas duras que este modulo NO permite romper:
  * Nunca pide una URL que robots.txt prohiba para nuestro user-agent.
  * Nunca ignora Crawl-delay (usa el mayor entre robots y el minimo local).
  * Nunca intenta resolver un challenge anti-bot: si lo detecta, aborta el dealer.
  * Nunca supera el presupuesto de peticiones por dealer y corrida.
"""
import gzip
import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request

from .robots import Robots

UA_NAME = "CarWatchBot/1.0"


class BotChallenge(Exception):
    """El sitio devolvio un muro anti-bot. Nos retiramos, no lo peleamos."""


class RobotsDenied(Exception):
    """robots.txt prohibe esta ruta. No se pide."""


class BudgetExhausted(Exception):
    pass


def build_user_agent(contact: str = "") -> str:
    base = f"{UA_NAME} (rastreador personal de inventario usado; bajo volumen)"
    if contact.strip():
        base = f"{UA_NAME} (rastreador personal de inventario usado; bajo volumen; contacto: {contact.strip()})"
    return base


_CHALLENGE_MARKERS = (
    "just a moment",
    "cf-browser-verification",
    "cf_chl_opt",
    "checking your browser",
    "__cf_chl",
    "attention required! | cloudflare",
    "verifying you are human",
)


def looks_like_challenge(body: str, status: int) -> bool:
    low = body[:4000].lower()
    if any(m in low for m in _CHALLENGE_MARKERS):
        return True
    if status in (403, 503) and ("cloudflare" in low or "captcha" in low):
        return True
    return False


class PoliteFetcher:
    def __init__(self, base, cache_dir, contact="", min_delay=6.0, timeout=30,
                 budget=90, respect_crawl_delay=True, log=print):
        self.base = base.rstrip("/")
        self.host = urllib.parse.urlsplit(self.base).netloc
        self.ua = build_user_agent(contact)
        self.min_delay = float(min_delay)
        self.timeout = timeout
        self.budget = int(budget)
        self.used = 0
        self.respect_crawl_delay = respect_crawl_delay
        self.log = log
        self.cache_dir = os.path.join(cache_dir, self.host.replace(":", "_"))
        os.makedirs(self.cache_dir, exist_ok=True)
        self._last_request_at = 0.0
        self._rp = None
        self._crawl_delay = None
        self.robots_missing = False
        self._loading_robots = False

    # ---------- robots ----------
    def _load_robots(self):
        if self._rp is not None or self._loading_robots:
            return
        self._loading_robots = True
        url = f"{self.base}/robots.txt"
        try:
            body, status, _ = self._raw_get(url, count_budget=False)
            if status == 200 and body.strip():
                self.robots_raw = body
                self._rp = Robots(body)
            else:
                self.robots_missing = True
                self._rp = Robots("")
        except Exception as exc:
            self.log(f"    robots.txt no legible ({exc}); se asume permitido y se va MAS lento")
            self.robots_missing = True
            self._rp = Robots("")
        finally:
            self._loading_robots = False

        delay = self._rp.crawl_delay(self.ua) if self.respect_crawl_delay else None
        if delay is None and self.robots_missing:
            delay = 10.0
        self._crawl_delay = float(delay) if delay else 0.0

    @property
    def effective_delay(self):
        self._load_robots()
        return max(self.min_delay, self._crawl_delay or 0.0)

    def allowed(self, url):
        self._load_robots()
        try:
            return self._rp.can_fetch(self.ua, url)
        except Exception:
            return False      # ante la duda, NO se pide

    # ---------- cache condicional ----------
    def _cache_paths(self, url):
        import hashlib
        h = hashlib.sha256(url.encode()).hexdigest()[:24]
        return (os.path.join(self.cache_dir, h + ".body"),
                os.path.join(self.cache_dir, h + ".meta"))

    def _read_meta(self, url):
        _, mp = self._cache_paths(url)
        try:
            with open(mp) as fh:
                return json.load(fh)
        except Exception:
            return {}

    def _save(self, url, body, headers):
        bp, mp = self._cache_paths(url)
        try:
            with open(bp, "w", encoding="utf-8") as fh:
                fh.write(body)
            meta = {"etag": headers.get("ETag"),
                    "last_modified": headers.get("Last-Modified"),
                    "saved_at": time.time()}
            with open(mp, "w") as fh:
                json.dump(meta, fh)
        except Exception:
            pass

    def _cached_body(self, url):
        bp, _ = self._cache_paths(url)
        try:
            with open(bp, encoding="utf-8") as fh:
                return fh.read()
        except Exception:
            return None

    # ---------- HTTP ----------
    def _sleep_if_needed(self):
        if self._rp is None or self._loading_robots:
            delay = self.min_delay          # aun no sabemos el crawl-delay: usamos el minimo local
        else:
            delay = max(self.min_delay, self._crawl_delay or 0.0)
        wait = delay - (time.monotonic() - self._last_request_at)
        if wait > 0:
            time.sleep(wait)

    def _raw_get(self, url, count_budget=True, extra_headers=None):
        if count_budget:
            if self.used >= self.budget:
                raise BudgetExhausted(f"presupuesto de {self.budget} peticiones agotado en {self.host}")
            self.used += 1
        self._sleep_if_needed()
        headers = {
            "User-Agent": self.ua,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-CA,en;q=0.9,fr-CA;q=0.8",
            "Accept-Encoding": "gzip",
            "Connection": "close",
        }
        if extra_headers:
            headers.update(extra_headers)
        req = urllib.request.Request(url, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                raw = resp.read()
                if resp.headers.get("Content-Encoding") == "gzip":
                    raw = gzip.decompress(raw)
                body = raw.decode(resp.headers.get_content_charset() or "utf-8", errors="replace")
                return body, resp.status, resp.headers
        except urllib.error.HTTPError as e:
            raw = b""
            try:
                raw = e.read()
                if e.headers.get("Content-Encoding") == "gzip":
                    raw = gzip.decompress(raw)
            except Exception:
                pass
            body = raw.decode("utf-8", errors="replace")
            return body, e.code, e.headers or {}
        finally:
            self._last_request_at = time.monotonic()

    def get(self, path_or_url, retries=2):
        url = path_or_url if path_or_url.startswith("http") else self.base + path_or_url
        if not self.allowed(url):
            raise RobotsDenied(f"robots.txt prohibe {url} — no se pide")

        meta = self._read_meta(url)
        cond = {}
        if meta.get("etag"):
            cond["If-None-Match"] = meta["etag"]
        if meta.get("last_modified"):
            cond["If-Modified-Since"] = meta["last_modified"]

        attempt = 0
        while True:
            body, status, headers = self._raw_get(url, extra_headers=cond)

            if status == 304:
                cached = self._cached_body(url)
                if cached is not None:
                    return cached, True   # (contenido, sin_cambios)
                cond = {}
                continue

            if looks_like_challenge(body, status):
                raise BotChallenge(f"{self.host} devolvio un muro anti-bot en {url}")

            if status == 429 or 500 <= status < 600:
                attempt += 1
                if attempt > retries:
                    raise urllib.error.HTTPError(url, status, "sin reintentos restantes", headers, None)
                retry_after = 0
                try:
                    retry_after = int((headers or {}).get("Retry-After", 0))
                except Exception:
                    retry_after = 0
                backoff = max(retry_after, self.effective_delay * (2 ** attempt))
                self.log(f"    HTTP {status} en {url} — esperando {backoff:.0f}s")
                time.sleep(min(backoff, 120))
                continue

            if status != 200:
                raise urllib.error.HTTPError(url, status, "estado inesperado", headers, None)

            self._save(url, body, headers or {})
            return body, False
