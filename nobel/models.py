"""Small domain model used by the importer (not just demonstration classes)."""
from __future__ import annotations
from dataclasses import dataclass, field
from datetime import date
from html import unescape
from html.parser import HTMLParser
import math

CATEGORIES = {
    'Physics': ('phy', 'Физика', '#487FA5'),
    'Chemistry': ('che', 'Химия', '#2D8D82'),
    'Physiology or Medicine': ('med', 'Медицина', '#BD6574'),
    'Literature': ('lit', 'Литература', '#9372B4'),
    'Peace': ('pea', 'Мир', '#B28C40'),
    'Economic Sciences': ('eco', 'Экономика', '#C77748'),
}

class _Text(HTMLParser):
    def __init__(self):
        super().__init__(); self.parts = []
    def handle_data(self, data):
        self.parts.append(data)

def text(value, lang='en'):
    if isinstance(value, dict):
        value = value.get(lang) or value.get('en') or ''
    if value is None:
        return ''
    parser = _Text(); parser.feed(str(value))
    return unescape(''.join(parser.parts)).strip()

def year(value):
    try:
        y = int(str(value)[:4])
        return y if y > 0 else None
    except (ValueError, TypeError):
        return None

def full_date(value):
    try:
        return date.fromisoformat(value)
    except (ValueError, TypeError):
        return None

def age_at(birth, awarded, award_year):
    """dateAwarded is the API award/decision date, not assumed ceremony date."""
    b, a = full_date(birth), full_date(awarded)
    if b and a:
        age = a.year - b.year - ((a.month, a.day) < (b.month, b.day))
        return (age, 'exact') if age >= 0 else (None, 'unknown')
    if year(birth):
        age = int(award_year) - year(birth)
        return (age, 'year_estimate') if age >= 0 else (None, 'unknown')
    return None, 'unknown'

@dataclass(frozen=True)
class GeoPoint:
    lat: float
    lon: float
    def __post_init__(self):
        if not (math.isfinite(self.lat) and math.isfinite(self.lon) and -90 <= self.lat <= 90 and -180 <= self.lon <= 180):
            raise ValueError('Invalid geographic coordinates')
    def __str__(self):
        return f'{self.lat:.4f}, {self.lon:.4f}'
    @classmethod
    def from_api(cls, value):
        try:
            return cls(float(value['latitude']), float(value['longitude']))
        except (KeyError, TypeError, ValueError):
            return None

@dataclass
class Place:
    city: str = ''
    country: str = ''
    city_now: str = ''
    country_now: str = ''
    continent: str = ''
    point: GeoPoint | None = None
    raw: dict = field(default_factory=dict)
    @classmethod
    def from_api(cls, value):
        value = value or {}
        # Never substitute a country centroid for a city coordinate.
        return cls(text(value.get('city')), text(value.get('country')),
                   text(value.get('cityNow')) or text(value.get('city')),
                   text(value.get('countryNow')) or text(value.get('country')),
                   text(value.get('continent')), GeoPoint.from_api(value.get('cityNow', {})), value)
    def __str__(self):
        return ', '.join(x for x in (self.city_now, self.country_now) if x) or 'Не указано'

@dataclass(eq=False)
class Entity:
    id: str
    name: str
    def __eq__(self, other):
        if not isinstance(other, Entity):
            return NotImplemented
        return type(self) is type(other) and self.id == other.id
    def __hash__(self):
        return hash((type(self), self.id))
    def __str__(self):
        return self.name

@dataclass
class Award:
    scheme: str
    year: int
    category: str
    @property
    def key(self):
        code = CATEGORIES.get(self.category, (self.category,))[0]
        return f'{self.scheme}:{self.year}:{code}'

@dataclass
class NobelPrize(Award):
    raw: dict = field(default_factory=dict)
    @classmethod
    def from_api(cls, raw):
        return cls('nobel', int(raw['awardYear']), text(raw['category']), raw)

@dataclass
class AwardCredit:
    prize: NobelPrize
    raw: dict
    affiliations: list[Place] = field(default_factory=list)
    @classmethod
    def from_api(cls, raw):
        return cls(NobelPrize.from_api(raw), raw,
                   [Place.from_api(a) for a in raw.get('affiliations', [])])

@dataclass(eq=False)
class Laureate(Entity):
    raw: dict = field(default_factory=dict)
    birth: Place = field(default_factory=Place)
    death: Place = field(default_factory=Place)
    founded: Place = field(default_factory=Place)
    awards: list[AwardCredit] = field(default_factory=list)
    @property
    def kind(self):
        return 'organization' if 'orgName' in self.raw else 'person'
    @classmethod
    def from_api(cls, raw):
        return cls(str(raw['id']), text(raw.get('knownName') or raw.get('orgName') or raw.get('fullName')),
                   raw, Place.from_api(raw.get('birth', {}).get('place')),
                   Place.from_api(raw.get('death', {}).get('place')),
                   Place.from_api(raw.get('founded', {}).get('place')),
                   [AwardCredit.from_api(a) for a in raw.get('nobelPrizes', [])])

class NobelDataset:
    def __init__(self, laureates, prizes):
        self.laureates = [Laureate.from_api(x) for x in laureates]
        self.prizes = [NobelPrize.from_api(x) for x in prizes]
    def __len__(self):
        return len(self.laureates)
    def __iter__(self):
        return iter(self.laureates)
    def __getitem__(self, index):
        return self.laureates[index]
    def validate(self):
        if not self.laureates or not self.prizes:
            raise ValueError('Empty snapshot; existing database is preserved')
        ids = [l.id for l in self]; keys = [p.key for p in self.prizes]
        if len(ids) != len(set(ids)) or len(keys) != len(set(keys)):
            raise ValueError('Duplicate source identifiers')
        from_laureates = [(l.id, c.prize.key) for l in self for c in l.awards]
        from_prizes = [(str(l['id']), p.key) for p in self.prizes for l in p.raw.get('laureates', [])]
        if len(from_laureates) != len(set(from_laureates)) or set(from_laureates) != set(from_prizes):
            raise ValueError('The two API endpoints disagree; retry later')
        if not set(k for _, k in from_laureates).issubset(keys):
            raise ValueError('Missing prize records')
