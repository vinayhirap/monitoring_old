"""Numerology engine — Pythagorean + Chaldean systems.

Computes:
  - Compound number, root number for a symbol/name
  - Date numerology (root number for any date)
  - Compatibility score between symbol and date
  - Planetary ruler mapping (1=Sun, 2=Moon, ..., 9=Mars)

Used as a confluence signal — never as standalone trade rationale.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime


PYTHAGOREAN = {
    "A": 1, "B": 2, "C": 3, "D": 4, "E": 5, "F": 6, "G": 7, "H": 8, "I": 9,
    "J": 1, "K": 2, "L": 3, "M": 4, "N": 5, "O": 6, "P": 7, "Q": 8, "R": 9,
    "S": 1, "T": 2, "U": 3, "V": 4, "W": 5, "X": 6, "Y": 7, "Z": 8,
}

# Chaldean: skips 9; 9 is regarded as sacred and not assigned to letters.
CHALDEAN = {
    "A": 1, "I": 1, "J": 1, "Q": 1, "Y": 1,
    "B": 2, "K": 2, "R": 2,
    "C": 3, "G": 3, "L": 3, "S": 3,
    "D": 4, "M": 4, "T": 4,
    "E": 5, "H": 5, "N": 5, "X": 5,
    "U": 6, "V": 6, "W": 6,
    "O": 7, "Z": 7,
    "F": 8, "P": 8,
}

PLANETARY_RULER = {
    1: ("Sun",     "leadership, vitality, conviction; bullish on large-cap leaders"),
    2: ("Moon",    "fluctuating; intraday volatility; sentiment-driven"),
    3: ("Jupiter", "expansion, optimism; favors growth/finance sectors"),
    4: ("Rahu",    "speculative, sudden moves; uneven; tech/disruption"),
    5: ("Mercury", "communication & commerce; favors media, IT, brokerage"),
    6: ("Venus",   "luxury, FMCG, autos; smooth uptrends"),
    7: ("Ketu",    "mystery, sudden shocks; pharma, biotech, esoteric"),
    8: ("Saturn",  "discipline, slow grind; PSU, infra, metals; karmic"),
    9: ("Mars",    "energy, conflict; defense, energy, oil; volatile"),
}


def _digit_sum(n: int) -> int:
    while n > 9 and n not in (11, 22, 33):     # preserve master numbers
        n = sum(int(d) for d in str(n))
    return n


def _compound(text: str, table: dict[str, int]) -> int:
    return sum(table.get(c, 0) for c in text.upper() if c.isalpha())


@dataclass
class NameReading:
    system: str
    compound: int
    root: int
    ruler: str
    interpretation: str

    def to_dict(self) -> dict:
        return self.__dict__


def _full_reduce(n: int) -> int:
    """Always reduce to a single digit (master numbers collapsed for ruler lookup)."""
    while n > 9:
        n = sum(int(d) for d in str(n))
    return n


def reading(name: str, system: str = "pythagorean") -> NameReading:
    table = PYTHAGOREAN if system == "pythagorean" else CHALDEAN
    comp = _compound(name, table)
    root = _digit_sum(comp)                           # may be a master number (11/22/33)
    ruler_key = _full_reduce(root)                    # always 1..9 for the ruler table
    ruler, interp = PLANETARY_RULER.get(ruler_key, ("Unknown", "n/a"))
    return NameReading(system=system, compound=comp, root=root, ruler=ruler, interpretation=interp)


def date_number(d: date | datetime) -> int:
    if isinstance(d, datetime):
        d = d.date()
    return _digit_sum(d.day + d.month + d.year)


def life_path(dob: date) -> int:
    """Trader personal life-path number from date of birth."""
    return _digit_sum(_digit_sum(dob.day) + _digit_sum(dob.month) + _digit_sum(dob.year))


def compatibility(symbol_root: int, date_root: int) -> float:
    """0..100 compatibility — based on classical numerology friendly/neutral/enemy pairs."""
    friendly = {
        1: {1, 3, 5, 9},
        2: {2, 4, 7, 9},
        3: {1, 3, 5, 7, 9},
        4: {2, 4, 7, 8},
        5: {1, 5, 6, 9},
        6: {3, 6, 9},
        7: {2, 3, 7, 9},
        8: {4, 6, 8},
        9: {1, 3, 6, 9},
    }
    if symbol_root == date_root:
        return 90.0
    if date_root in friendly.get(symbol_root, set()):
        return 75.0
    enemy_pairs = {(4, 5), (5, 4), (8, 9), (9, 8), (1, 8), (8, 1)}
    if (symbol_root, date_root) in enemy_pairs:
        return 25.0
    return 50.0


# ============================================================================
# Aggregate
# ============================================================================

@dataclass
class NumerologyScore:
    symbol: str
    pythagorean: dict
    chaldean: dict
    today_date_number: int
    compatibility_with_today: float
    planetary_ruler: str
    score: float                  # 0..100 (higher = better day for symbol)
    bias: str
    interpretation: str
    reasons: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return self.__dict__


def analyze(symbol: str, ref_date: date | None = None) -> NumerologyScore:
    if ref_date is None:
        ref_date = date.today()

    pyth = reading(symbol, "pythagorean")
    chal = reading(symbol, "chaldean")
    d_num = date_number(ref_date)
    compat = compatibility(pyth.root, d_num)

    # Score derives from compatibility + favourable rulers
    score = compat
    reasons: list[str] = [
        f"Symbol root {pyth.root} (Pythagorean) ruled by {pyth.ruler}",
        f"Today's date number {d_num} — compatibility {compat:.0f}/100",
    ]

    # Boost / penalty for specific date numbers
    if d_num in (1, 3, 5, 6, 9):
        score += 5
        reasons.append(f"Date number {d_num} historically favorable for momentum trades")
    elif d_num in (4, 8):
        score -= 5
        reasons.append(f"Date number {d_num} (Saturn/Rahu) — discipline / restriction")

    # Master numbers
    if pyth.compound in (11, 22, 33):
        score += 5
        reasons.append(f"Master number {pyth.compound} — heightened energy")

    score = max(0.0, min(100.0, score))
    bias = "BULLISH" if score >= 60 else "BEARISH" if score <= 40 else "NEUTRAL"

    return NumerologyScore(
        symbol=symbol,
        pythagorean=pyth.to_dict(),
        chaldean=chal.to_dict(),
        today_date_number=d_num,
        compatibility_with_today=compat,
        planetary_ruler=pyth.ruler,
        score=score,
        bias=bias,
        interpretation=pyth.interpretation,
        reasons=reasons,
    )
