"""Hand-picked Riyadh districts used as search centers.

Google Maps' `/maps/search` spreads results outward from the query
point, so a single well-placed centroid per district gives reasonable
coverage of that district (~1.5–3 km radius depending on density).
Grid tiling over the whole bbox would also work but floods the queue
with many low-yield cells in the outskirts; ~25 curated districts give
us meaningful coverage of where people actually live and eat.

Coordinates are approximate district centroids — within a few hundred
metres is fine. Names in Arabic are there so the raw payload shows
which area produced a row. Verify any single coordinate you're building
analytics off of against a map.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class District:
    slug: str
    name_ar: str
    lat: float
    lng: float

    def coords(self) -> str:
        return f"{self.lat:.6f},{self.lng:.6f}"


RIYADH_DISTRICTS: list[District] = [
    # Central / business spine
    District("olaya",         "العليا",         24.7136, 46.6753),
    District("sulaymaniyah",  "السليمانية",     24.7010, 46.6810),
    District("wurud",         "الورود",         24.7210, 46.6700),
    District("maathar",       "المعذر",          24.6953, 46.6723),
    District("khuzama",       "الخزامى",         24.6890, 46.6770),
    District("wazarat",       "الوزارات",        24.6580, 46.7100),

    # Older downtown / historic
    District("malaz",         "الملز",          24.6755, 46.7352),
    District("deerah",        "الديرة",         24.6320, 46.7160),
    District("batha",         "البطحاء",         24.6310, 46.7190),
    District("oud",           "العود",          24.6350, 46.7020),

    # North / new developments
    District("sahafah",       "الصحافة",        24.7890, 46.6460),
    District("rabi",          "الربيع",         24.8150, 46.6850),
    District("murooj",        "المروج",         24.7750, 46.6700),
    District("nakheel",       "النخيل",         24.7620, 46.6380),
    District("king_fahd",     "الملك فهد",      24.7700, 46.6450),
    District("yasmin",        "الياسمين",       24.8250, 46.6400),
    District("narjis",        "النرجس",         24.8680, 46.7080),
    District("arid",          "العارض",         24.8950, 46.7200),
    District("qurtubah",      "قرطبة",          24.7920, 46.7340),
    District("rahmaniyah",    "الرحمانية",       24.7200, 46.6430),

    # East
    District("rawdah",        "الروضة",         24.7430, 46.7890),
    District("hamra",         "الحمراء",        24.7400, 46.8200),
    District("mursalat",      "المرسلات",       24.7750, 46.7080),
    District("yarmuk",        "اليرموك",        24.7400, 46.8050),

    # West
    District("malqa",         "الملقا",         24.8050, 46.6100),
    District("hittin",        "حطين",           24.8000, 46.5700),
    District("aqiq",          "العقيق",         24.7630, 46.6110),
    District("irqah",         "عرقة",           24.6800, 46.5620),

    # South
    District("shifa",         "الشفا",          24.5620, 46.6950),
    District("mansurah",      "المنصورة",       24.5930, 46.7470),
]
