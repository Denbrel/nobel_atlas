"""Предметная модель, используемая импортёром: наследование, композиция и специальные методы."""

from __future__ import annotations
from dataclasses import dataclass, field
from datetime import date
from html import unescape
from html.parser import HTMLParser
import math

CATEGORIES = {
    "Physics": ("phy", "Физика", "#487FA5"),
    "Chemistry": ("che", "Химия", "#2D8D82"),
    "Physiology or Medicine": ("med", "Медицина", "#BD6574"),
    "Literature": ("lit", "Литература", "#9372B4"),
    "Peace": ("pea", "Мир", "#B28C40"),
    "Economic Sciences": ("eco", "Экономика", "#C77748"),
}


class _Text(HTMLParser):
    """Минимальный HTML-парсер для превращения текстов API в обычный текст."""

    def __init__(self):
        """Подготовить буфер текстовых фрагментов."""
        super().__init__()
        self.parts = []

    def handle_data(self, data):
        """Собирать текст, игнорируя разметку и атрибуты HTML."""
        self.parts.append(data)


def text(value, lang="en"):
    """Выбрать язык с запасным английским вариантом и удалить HTML-разметку."""
    if isinstance(value, dict):
        value = value.get(lang) or value.get("en") or ""
    if value is None:
        return ""
    parser = _Text()
    parser.feed(str(value))
    return unescape("".join(parser.parts)).strip()


def year(value):
    """Извлечь известный год даже из неполной даты вида YYYY-00-00."""
    try:
        y = int(str(value)[:4])
        return y if y > 0 else None
    except (ValueError, TypeError):
        return None


def full_date(value):
    """Вернуть календарную дату только при известных и корректных дне и месяце."""
    try:
        return date.fromisoformat(value)
    except (ValueError, TypeError):
        return None


def age_at(birth, awarded, award_year):
    """dateAwarded is the API award/decision date, not assumed ceremony date."""
    b, a = full_date(birth), full_date(awarded)
    if b and a:
        age = a.year - b.year - ((a.month, a.day) < (b.month, b.day))
        return (age, "exact") if age >= 0 else (None, "unknown")
    if year(birth):
        age = int(award_year) - year(birth)
        return (age, "year_estimate") if age >= 0 else (None, "unknown")
    return None, "unknown"


@dataclass(frozen=True)
class GeoPoint:
    """Неизменяемая пара координат с проверкой географических диапазонов."""

    lat: float
    lon: float

    def __post_init__(self):
        """Отклонить бесконечные значения, NaN и выход за диапазон широты/долготы."""
        if not (
            math.isfinite(self.lat)
            and math.isfinite(self.lon)
            and -90 <= self.lat <= 90
            and -180 <= self.lon <= 180
        ):
            raise ValueError("Invalid geographic coordinates")

    def __str__(self):
        """Форматировать координаты для подписи в карточке."""
        return f"{self.lat:.4f}, {self.lon:.4f}"

    @classmethod
    def from_api(cls, value):
        """Прочитать координаты, сохраняя валидные нули; неверные значения дают None."""
        try:
            return cls(float(value["latitude"]), float(value["longitude"]))
        except (KeyError, TypeError, ValueError):
            return None


@dataclass
class Place:
    """Место с историческими и современными названиями и необязательной точкой."""

    city: str = ""
    country: str = ""
    city_now: str = ""
    country_now: str = ""
    continent: str = ""
    point: GeoPoint | None = None
    raw: dict = field(default_factory=dict)

    @classmethod
    def from_api(cls, value):
        """Нормализовать место; не подставлять центр страны вместо координат города."""
        value = value or {}
        # Never substitute a country centroid for a city coordinate.
        return cls(
            text(value.get("city")),
            text(value.get("country")),
            text(value.get("cityNow")) or text(value.get("city")),
            text(value.get("countryNow")) or text(value.get("country")),
            text(value.get("continent")),
            GeoPoint.from_api(value.get("cityNow", {})),
            value,
        )

    def __str__(self):
        """Составить человекочитаемую подпись города и страны."""
        return (
            ", ".join(x for x in (self.city_now, self.country_now) if x) or "Не указано"
        )


@dataclass(eq=False)
class Entity:
    """Базовая сущность: равенство определяется типом и устойчивым ID."""

    id: str
    name: str

    def __eq__(self, other):
        """Сравнить сущности одного типа по идентификатору, а не по имени."""
        if not isinstance(other, Entity):
            return NotImplemented
        return type(self) is type(other) and self.id == other.id

    def __hash__(self):
        """Согласовать хэш с правилом равенства для множеств и словарей."""
        return hash((type(self), self.id))

    def __str__(self):
        """Вернуть отображаемое имя сущности."""
        return self.name


@dataclass
class Award:
    """Общие признаки премии; поле scheme оставляет место другим источникам."""

    scheme: str
    year: int
    category: str

    @property
    def key(self):
        """Построить устойчивый ключ из схемы, года и категории."""
        code = CATEGORIES.get(self.category, (self.category,))[0]
        return f"{self.scheme}:{self.year}:{code}"


@dataclass
class NobelPrize(Award):
    """Нобелевская премия расширяет общую модель полным исходным JSON."""

    raw: dict = field(default_factory=dict)

    @classmethod
    def from_api(cls, raw):
        """Создать премию из официальной записи, не теряя неизвестные поля."""
        return cls("nobel", int(raw["awardYear"]), text(raw["category"]), raw)


@dataclass
class AwardCredit:
    """Одно награждение: премия, доля, формулировка и все аффилиации."""

    prize: NobelPrize
    raw: dict
    affiliations: list[Place] = field(default_factory=list)

    @classmethod
    def from_api(cls, raw):
        """Сохранить все аффилиации, а не только первую."""
        return cls(
            NobelPrize.from_api(raw),
            raw,
            [Place.from_api(a) for a in raw.get("affiliations", [])],
        )


@dataclass(eq=False)
class Laureate(Entity):
    """Лауреат содержит места и список награждений: пример композиции."""

    raw: dict = field(default_factory=dict)
    birth: Place = field(default_factory=Place)
    death: Place = field(default_factory=Place)
    founded: Place = field(default_factory=Place)
    awards: list[AwardCredit] = field(default_factory=list)

    @property
    def kind(self):
        """Отличить организацию от человека по структуре официальной записи."""
        return "organization" if "orgName" in self.raw else "person"

    @classmethod
    def from_api(cls, raw):
        """Собрать лауреата, события жизни/основания и все награждения."""
        return cls(
            str(raw["id"]),
            text(raw.get("knownName") or raw.get("orgName") or raw.get("fullName")),
            raw,
            Place.from_api(raw.get("birth", {}).get("place")),
            Place.from_api(raw.get("death", {}).get("place")),
            Place.from_api(raw.get("founded", {}).get("place")),
            [AwardCredit.from_api(a) for a in raw.get("nobelPrizes", [])],
        )


class NobelDataset:
    """Полный набор двух endpoint с проверкой их взаимной согласованности."""

    def __init__(self, laureates, prizes):
        """Создать рабочие объекты модели из первичных JSON."""
        self.laureates = [Laureate.from_api(x) for x in laureates]
        self.prizes = [NobelPrize.from_api(x) for x in prizes]

    def __len__(self):
        """Вернуть число уникальных записей лауреатов в наборе."""
        return len(self.laureates)

    def __iter__(self):
        """Разрешить обход лауреатов обычным циклом for."""
        return iter(self.laureates)

    def __getitem__(self, index):
        """Разрешить индексирование и срезы набора лауреатов."""
        return self.laureates[index]

    def validate(self):
        """Отклонить пустые наборы, дубли ID и расхождения endpoint."""
        if not self.laureates or not self.prizes:
            raise ValueError("Empty snapshot; existing database is preserved")
        ids = [l.id for l in self]
        keys = [p.key for p in self.prizes]
        if len(ids) != len(set(ids)) or len(keys) != len(set(keys)):
            raise ValueError("Duplicate source identifiers")
        from_laureates = [(l.id, c.prize.key) for l in self for c in l.awards]
        from_prizes = [
            (str(l["id"]), p.key)
            for p in self.prizes
            for l in p.raw.get("laureates", [])
        ]
        if len(from_laureates) != len(set(from_laureates)) or set(
            from_laureates
        ) != set(from_prizes):
            raise ValueError("The two API endpoints disagree; retry later")
        if not set(k for _, k in from_laureates).issubset(keys):
            raise ValueError("Missing prize records")
