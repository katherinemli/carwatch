"""Interprete de robots.txt con comodines.

urllib.robotparser no soporta '*' ni '$': compara con startswith. Con eso,
reglas como 'Disallow: /*?*' (todo Sm360) se ignoran silenciosamente y el
scraper se cree autorizado. Aqui se implementa el comportamiento real:

  * comodin '*' y ancla final '$'
  * gana la regla de patron mas largo; en empate gana Allow (criterio de Google)
  * grupos por User-agent, con vuelta a '*'
  * lineas de directiva huerfanas tras una linea en blanco se reunen con su
    grupo, en vez de aprovechar el tecnicismo para ignorarlas
"""
import re


def _merge_orphan_rules(text):
    lines = text.splitlines()
    out = []
    for i, line in enumerate(lines):
        if line.strip():
            out.append(line)
            continue
        nxt = None
        for j in range(i + 1, len(lines)):
            cand = lines[j].strip()
            if not cand or cand.startswith("#"):
                continue
            nxt = cand.lower()
            break
        seen_agent = any(l.strip().lower().startswith("user-agent") for l in out)
        if nxt and seen_agent and not nxt.startswith("user-agent"):
            continue
        out.append(line)
    return out


def _to_regex(pattern):
    if not pattern:
        return None
    anchored_end = pattern.endswith("$")
    if anchored_end:
        pattern = pattern[:-1]
    parts = [re.escape(p) for p in pattern.split("*")]
    rx = ".*".join(parts)
    return re.compile("^" + rx + (".*$" if not anchored_end else "$"))


class Group:
    def __init__(self):
        self.agents = []
        self.rules = []          # (allow: bool, raw_pattern: str, regex)
        self.crawl_delay = None

    def add_rule(self, allow, pattern):
        rx = _to_regex(pattern)
        if rx is not None:
            self.rules.append((allow, pattern, rx))


class Robots:
    def __init__(self, text=""):
        self.groups = []
        self.raw = text or ""
        self.empty = not (text or "").strip()
        self._parse(self.raw)

    def _parse(self, text):
        current = None
        expecting_agent = False
        for raw_line in _merge_orphan_rules(text):
            if not raw_line.strip():
                current = None            # solo una linea VACIA cierra el grupo
                expecting_agent = False
                continue
            line = raw_line.split("#", 1)[0].strip()
            if not line or ":" not in line:
                continue                  # una linea de solo comentario no cierra nada
            field, _, value = line.partition(":")
            field = field.strip().lower()
            value = value.strip()

            if field == "user-agent":
                if current is None or not expecting_agent:
                    current = Group()
                    self.groups.append(current)
                    expecting_agent = True
                current.agents.append(value.lower())
            elif field in ("disallow", "allow"):
                expecting_agent = False
                if current is None:
                    continue
                if field == "disallow" and value == "":
                    continue          # 'Disallow:' vacio = permitir todo
                current.add_rule(field == "allow", value)
            elif field in ("crawl-delay", "crawl_delay"):
                expecting_agent = False
                if current is None:
                    continue
                try:
                    current.crawl_delay = float(value)
                except ValueError:
                    pass

    # ------------------------------------------------------------------
    def _select(self, useragent):
        ua = (useragent or "").split("/")[0].strip().lower()
        best, star = None, None
        for g in self.groups:
            for a in g.agents:
                if a == "*":
                    star = star or g
                elif a and a in ua:
                    if best is None or len(a) > max((len(x) for x in best.agents if x != "*"), default=0):
                        best = g
        return best or star

    def crawl_delay(self, useragent):
        g = self._select(useragent)
        return g.crawl_delay if g else None

    def can_fetch(self, useragent, path):
        """path puede ser una URL completa o una ruta."""
        g = self._select(useragent)
        if g is None:
            return True
        if "://" in path:
            from urllib.parse import urlsplit
            sp = urlsplit(path)
            path = sp.path or "/"
            if sp.query:
                path += "?" + sp.query
        if not path.startswith("/"):
            path = "/" + path

        winner = None      # (longitud_patron, allow)
        for allow, pattern, rx in g.rules:
            if rx.match(path):
                key = len(pattern)
                if winner is None or key > winner[0] or (key == winner[0] and allow):
                    winner = (key, allow)
        return True if winner is None else winner[1]
