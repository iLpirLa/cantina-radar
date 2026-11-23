"""Parsing dei titoli dei lotti di vino Catawiki.

I titoli Catawiki seguono quasi sempre lo schema:
    "<annata> <Produttore>[, <Cuvée>] - <Denominazione/Classificazione> [- ...] - <N> Bottle(s) (<formato>L)"
Esempi:
    2008 Château Lynch Bages - Pauillac 5ème Grand Cru Classé - 1 Bottle (0.75L)
    2012 Fritz Haag, GK - Brauneberger Juffer Sonnenuhr - Mosel Auslese, Goldkapsel - 2 Bottles (0.75L)
    Domaine Vincent Paris ; Domaine Paul Jaboulet Ainé - Rhône - 4 Bottles (0.75L)
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field, asdict

STANDARD_BOTTLE_L = 0.75

# "6 Bottles (0.75L)", "1 Magnum (1.5L)", "2 Half Bottles (0.375L)", "1 Bottle (75cl)"
_QTY_RE = re.compile(
    r"(\d+)\s*(?:x\s*)?([A-Za-zÀ-ÿ][A-Za-zÀ-ÿ\- ]{0,30}?)?\s*\(\s*([\d.,]+)\s*(cl|ml|lt|litri|litro|litres?|liters?|l)\s*\)",
    re.IGNORECASE,
)
# Formati senza capacità esplicita
_NAMED_SIZES = {
    "half bottle": 0.375, "demi": 0.375, "magnum": 1.5, "double magnum": 3.0,
    "jeroboam": 3.0, "rehoboam": 4.5, "imperial": 6.0, "methuselah": 6.0,
    "mathusalem": 6.0, "salmanazar": 9.0, "balthazar": 12.0, "nebuchadnezzar": 15.0,
}
_NAMED_QTY_RE = re.compile(
    r"(\d+)\s+(half bottles?|double magnums?|magnums?|jeroboams?|rehoboams?|imperials?|"
    r"methuselahs?|mathusalems?|salmanazars?|balthazars?|nebuchadnezzars?|bottles?)\b",
    re.IGNORECASE,
)
# Fallback sullo slug dell'URL: "...-1-bottle-0-75l" / "...-6-bottles-0-75l"
_SLUG_QTY_RE = re.compile(r"(\d+)-([a-z-]+?)-(\d+)-(\d+)l(?:-|$)")

_VINTAGE = r"(?:18[5-9]\d|19\d\d|20[0-4]\d)"
_LEAD_VINTAGE_RE = re.compile(rf"^\s*({_VINTAGE})\s+")
_MULTI_VINTAGE_RE = re.compile(rf"^\s*({_VINTAGE})\s*(?:&|,|/|and|-|e)\s*({_VINTAGE})\b", re.IGNORECASE)
_INLINE_VINTAGE_RE = re.compile(rf"\b({_VINTAGE})\b")
# parole che indicano un lotto con vini diversi (anche dello stesso produttore)
_MIXED_WORDS_RE = re.compile(
    r"\b(mix|mixed|misto|mista|misti|miste|assortit[oaie]|assortiment|assortment|selezione di|selection of|"
    r"collezione|collection|verticale|vertical|degustazione|tasting set|cofanetto con|set di \d|lotto di vini|"
    r"vari produttori|various|diversi|different wines?|vins divers)\b", re.I)
_COUNT_X_RE = re.compile(r"\b\d+\s*x\s+\S", re.I)
_NV_RE = re.compile(r"\b(?:N\.?V\.?|non[- ]vintage|sans ann[ée]e|senza annata)\b", re.IGNORECASE)

# Parole da ignorare nel calcolo della chiave del vino
_STOPWORDS = {
    "chateau", "ch", "domaine", "dom", "weingut", "tenuta", "azienda", "agricola", "cantina",
    "cantine", "bodegas", "bodega", "maison", "clos_", "the", "de", "du", "des", "la", "le",
    "les", "di", "del", "della", "dei", "e", "et", "and", "wines", "wine", "vini", "vino",
    "estate", "winery", "spa", "srl", "sa", "gmbh", "fattoria", "podere", "castello",
}
_CLASSIFICATION_WORDS = {
    "grand", "cru", "classe", "classes", "1er", "premier", "1eme", "2eme", "3eme", "4eme", "5eme",
    "2nd", "3rd", "4th", "5th", "aoc", "aop", "doc", "docg", "igt", "igp", "do", "doca", "vdp",
    "superieur", "superiore", "gran", "selection", "exceptionnel", "bourgeois",
}


def strip_accents(s: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKD", s) if not unicodedata.combining(c))


def norm_text(s: str) -> str:
    s = strip_accents(s or "").lower()
    s = s.replace("’", "'").replace("'", " ")
    s = re.sub(r"[^a-z0-9]+", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def _key_tokens(s: str, drop_classification: bool = False) -> list[str]:
    toks = [t for t in norm_text(s).split() if t not in _STOPWORDS]
    if drop_classification:
        toks = [t for t in toks if t not in _CLASSIFICATION_WORDS]
    return toks


@dataclass
class ParsedTitle:
    raw: str
    vintage: int | None = None
    nv: bool = False
    producer: str = ""
    cuvee: str = ""
    appellation: str = ""
    extra: list[str] = field(default_factory=list)
    bottles: int = 0
    total_liters: float = 0.0
    bottle_eq: float = 0.0          # equivalenti bottiglia da 0,75 L
    size_l: float | None = None     # formato se omogeneo
    mixed: bool = False
    ok: bool = False
    wine_name: str = ""             # nome normalizzato per il matching
    wine_key: str = ""              # chiave stabile (produttore|cuvée|denominazione)

    def to_dict(self) -> dict:
        return asdict(self)


def _to_liters(num: str, unit: str) -> float:
    v = float(num.replace(",", "."))
    unit = unit.lower()
    if unit.startswith("l"):
        return v
    if unit == "cl":
        return v / 100
    if unit == "ml":
        return v / 1000
    return v


def parse_quantity(text: str) -> tuple[int, float, float | None]:
    """Ritorna (numero bottiglie, litri totali, formato se omogeneo)."""
    bottles, liters, sizes = 0, 0.0, set()
    for m in _QTY_RE.finditer(text):
        n = int(m.group(1))
        size = _to_liters(m.group(3), m.group(4))
        if n <= 0 or n > 600 or not (0.05 <= size <= 30):
            continue
        bottles += n
        liters += n * size
        sizes.add(round(size, 3))
    if bottles == 0:
        for m in _NAMED_QTY_RE.finditer(text):
            n = int(m.group(1))
            name = m.group(2).lower().rstrip("s")
            size = _NAMED_SIZES.get(name, STANDARD_BOTTLE_L)
            bottles += n
            liters += n * size
            sizes.add(size)
    return bottles, liters, (sizes.pop() if len(sizes) == 1 else None)


def parse_slug_quantity(slug: str) -> tuple[int, float, float | None]:
    m = None
    for m in _SLUG_QTY_RE.finditer(slug or ""):
        pass
    if not m:
        return 0, 0.0, None
    n = int(m.group(1))
    name = m.group(2).replace("-", " ").rstrip("s")
    size = float(f"{m.group(3)}.{m.group(4)}")
    if name not in ("bottle", "bottles") and name in _NAMED_SIZES and size == 0:
        size = _NAMED_SIZES[name]
    return n, n * size, size


def parse_title(title: str, slug: str = "") -> ParsedTitle:
    p = ParsedTitle(raw=title or "")
    t = re.sub(r"\s+", " ", (title or "").strip())
    if not t and slug:
        # Ricostruzione dal solo slug: "2008-chateau-x-pauillac-1-bottle-0-75l"
        ms = list(_SLUG_QTY_RE.finditer(slug))
        if ms:
            n, liters, size = parse_slug_quantity(slug)
            body = slug[: ms[-1].start()].strip("-").replace("-", " ")
            t = f"{body} - {n} Bottles ({size}L)"
        else:
            t = slug.replace("-", " ")
    parts = [x.strip() for x in re.split(r"\s+[-–—]\s+", t) if x.strip()]
    if not parts:
        return p

    # Quantità: di solito l'ultima parte
    bottles, liters, size = parse_quantity(parts[-1])
    qty_in_last = bottles > 0
    if not qty_in_last:
        bottles, liters, size = parse_quantity(t)
    if bottles == 0 and slug:
        bottles, liters, size = parse_slug_quantity(slug)
    if qty_in_last:
        parts = parts[:-1]
    p.bottles, p.total_liters, p.size_l = bottles, round(liters, 3), size
    p.bottle_eq = round(liters / STANDARD_BOTTLE_L, 3) if liters else 0.0
    if not parts:
        return p

    head = parts[0]
    # Annata / multi-annata / NV
    if _MULTI_VINTAGE_RE.match(head):
        p.mixed = True
        m = _MULTI_VINTAGE_RE.match(head)
        head = head[m.end():].strip()
    else:
        m = _LEAD_VINTAGE_RE.match(head)
        if m:
            p.vintage = int(m.group(1))
            head = head[m.end():].strip()
        elif _NV_RE.search(t):
            p.nv = True
        else:
            inl = _INLINE_VINTAGE_RE.findall(head)
            if len(inl) == 1:
                p.vintage = int(inl[0])
            elif len(inl) > 1:
                p.mixed = True
    if _NV_RE.search(head):
        p.nv = True
        head = _NV_RE.sub("", head).strip(" ,")

    # Lotti misti: più produttori o più annate
    if ";" in head or " / " in head or re.search(rf"\b{_VINTAGE}\b.*\b{_VINTAGE}\b", head):
        p.mixed = True
    if len(_INLINE_VINTAGE_RE.findall(t)) > 1 and not p.vintage:
        p.mixed = True
    if _MIXED_WORDS_RE.search(t) or len(_COUNT_X_RE.findall(t)) >= 2:
        p.mixed = True

    if "," in head:
        prod, cuv = head.split(",", 1)
        p.producer, p.cuvee = prod.strip(), cuv.strip()
    else:
        p.producer = head.strip()
    if len(parts) > 1:
        p.appellation = parts[1]
        p.extra = parts[2:]

    name_bits = [p.producer, p.cuvee, p.appellation] + p.extra
    p.wine_name = " ".join(_key_tokens(" ".join(name_bits), drop_classification=True))
    key_bits = [
        "-".join(_key_tokens(p.producer)),
        "-".join(_key_tokens(p.cuvee)),
        "-".join(_key_tokens(p.appellation, drop_classification=True)),
    ]
    p.wine_key = "|".join(key_bits)
    p.ok = bool(p.producer) and p.bottle_eq > 0 and not p.mixed
    return p


# ---------------------------------------------------------------- tipologia
_TYPE_RULES = [
    ("spumante", r"champagne|franciacorta|cava\b|prosecco|cr[eé]mant|spumante|sekt|trento ?doc|metodo classico|"
                 r"blanc de (?:blancs|noirs)|extra brut|\bbrut\b|pas dos[eé]|dosage z[eé]ro|p[eé]tillant|lambrusco|"
                 r"dom p[eé]rignon|krug|cristal|bollinger|ruinart|taittinger|perl[eè]"),
    ("dolce", r"\bport\b|porto|sauternes|barsac|tokaj|passito|recioto|vin santo|vinsanto|madeira|sherry|jerez|"
              r"marsala|beerenauslese|trockenbeerenauslese|\btba\b|eiswein|ice ?wine|auslese|moscato|muscat|"
              r"banyuls|maury|rivesaltes|pedro xim[eé]nez|\bpx\b|vendanges tardives|s[eé]lection de grains nobles|"
              r"yquem|late harvest|sweet"),
    ("rosato", r"\bros[eé]\b|rosato|rosado|cerasuolo|chiaretto|tavel"),
    ("bianco", r"chardonnay|sauvignon blanc|\bsauvignon\b|riesling|chablis|meursault|montrachet|corton[- ]charlemagne|"
               r"pouilly|sancerre|gew[uü]rztraminer|pinot (?:grigio|gris|blanc|bianco)|vermentino|soave|gr[uü]ner|"
               r"weissburgunder|wei[sß]burgunder|albari[nñ]o|verdicchio|fiano|greco di tufo|timorasso|trebbiano|"
               r"chenin|viognier|condrieu|vouvray|savenni[eè]res|semillon|s[eé]millon|marsanne|roussanne|godello|"
               r"verdejo|friulano|ribolla|kerner|silvaner|m[uü]ller|\bbianco\b|\bblanc\b|\bweiss\b|\bwhite\b|"
               r"\bblanco\b|\bbranco\b"),
    # vitigni e colori rossi: decisivi
    ("rosso_forte", r"malbec|cabernet|merlot|pinot noir|pinot nero|sp[aä]tburgunder|syrah|shiraz|nebbiolo|sangiovese|"
                    r"zinfandel|montepulciano|aglianico|primitivo|nero d.avola|lagrein|teroldego|barbera|dolcetto|"
                    r"grenache|garnacha|tempranillo|carm[eé]n[eè]re|cannonau|refosco|sagrantino|corvina|"
                    r"\brosso\b|\brouge\b|\btinto\b|\bred\b|\brot\b"),
    # zone tipicamente rosse: contano solo se non c'è un vitigno o colore bianco
    ("rosso", r"barolo|barbaresco|brunello|chianti|bolgheri|sassicaia|tignanello|ornellaia|amarone|valpolicella|"
              r"pauillac|margaux|saint[- ]julien|saint[- ]est[eè]phe|pomerol|saint[- ][eé]milion|pessac|graves|"
              r"m[eé]doc|bordeaux|pommard|volnay|nuits|gevrey|vosne|chambolle|morey|clos de vougeot|beaune|"
              r"c[oô]te[- ]r[oô]tie|hermitage|cornas|ch[aâ]teauneuf|gigondas|vacqueyras|rioja|ribera|priorat|toro\b|"
              r"taurasi|langhe|roero|ghemme|gattinara|etna|morellino|vino nobile|bourgogne|burgundy|toscana|"
              r"rodano|rh[oô]ne|languedoc|mendoza|napa|maremma"),
]
_TYPE_RES = [(t, re.compile(rx, re.I)) for t, rx in _TYPE_RULES]
WINE_TYPES = {"rosso": "Rosso", "bianco": "Bianco", "rosato": "Rosato", "spumante": "Spumante",
              "dolce": "Dolce e fortificato", "": "Non determinato"}


def wine_type(title: str, category_id: int | None = None) -> str:
    """Tipologia dedotta dal titolo: rosso, bianco, rosato, spumante, dolce ('' se non determinabile)."""
    if category_id == 961:
        return "spumante"
    if category_id == 971:
        return "dolce"
    t = strip_accents(title or "")
    # le parole del vitigno/colore pesano più della denominazione (es. "Langhe Chardonnay" = bianco)
    for typ, rx in _TYPE_RES:
        if typ in ("spumante", "dolce", "rosato") and rx.search(t):
            return typ
    rx = dict(_TYPE_RES)
    if rx["rosso_forte"].search(t):
        return "rosso"
    if rx["bianco"].search(t):
        return "bianco"
    if rx["rosso"].search(t):
        return "rosso"
    return ""
