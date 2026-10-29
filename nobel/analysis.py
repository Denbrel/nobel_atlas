"""Чистые фильтры и аналитика: одна строка соответствует одному награждению."""

from dataclasses import dataclass, field
import math
import unicodedata
import pandas as pd
from .models import full_date, year
from .geography import CityIndex, add_origins, organization_locations

UNKNOWN = "Не указано"
GENDERS = {"male": "Мужчины", "female": "Женщины"}


def fold(value):
    """Нормализовать регистр и диакритику для поиска по разным написаниям."""
    return "".join(
        c
        for c in unicodedata.normalize("NFKD", str(value)).casefold()
        if not unicodedata.combining(c)
    )


def prepare(credits, affiliations, cache=None, residences=None):
    """Подготовить подписи, поиск, точность дат и общую географию происхождения."""
    df = add_origins(credits, affiliations, residences)
    df["gender_label"] = df["gender"].map(GENDERS).fillna(UNKNOWN)
    df.loc[df.kind == "organization", "gender_label"] = "Организации"
    df["kind_label"] = df.kind.map({"person": "Люди", "organization": "Организации"})
    for col in (
        "birth_city",
        "birth_country",
        "birth_country_historical",
        "birth_continent",
        "death_country",
        "death_city",
        "origin_city",
        "origin_country",
        "origin_continent",
    ):
        df[col] = df[col].replace("", UNKNOWN).fillna(UNKNOWN)
    df["decade"] = (df.award_year // 10) * 10
    df["birth_date_exact"] = df.birth_date.map(
        lambda value: full_date(value) is not None
    )
    df["organization_age"] = df.award_year - pd.to_numeric(
        df.founded_date.map(year), errors="coerce"
    )
    df.loc[df.kind.ne("organization"), "organization_age"] = float("nan")
    df["name_ru"] = df.wikidata_id.map(
        lambda q: (cache or {})
        .get(q, {})
        .get("data", {})
        .get("labels", {})
        .get("ru", {})
        .get("value", "")
    )
    df["description"] = df.wikidata_id.map(
        lambda q: description((cache or {}).get(q, {}).get("data", {}))
    )
    names = (
        affiliations.groupby("award_key")["name"].agg(" | ".join)
        if len(affiliations)
        else pd.Series(dtype=str)
    )
    df["institutions"] = df.award_key.map(names).fillna("")
    df["search_text"] = (
        df[
            [
                "name",
                "full_name",
                "name_ru",
                "motivation",
                "description",
                "institutions",
            ]
        ]
        .fillna("")
        .astype(str)
        .agg(" ".join, axis=1)
        .map(fold)
    )
    return df


def description(entity):
    """Выбрать русское описание Wikidata, а при его отсутствии английское."""
    descriptions = entity.get("descriptions", {})
    return (descriptions.get("ru") or descriptions.get("en") or {}).get("value", "")


@dataclass
class FilterSpec:
    """Значения фильтров без зависимости от виджетов Streamlit или HTTP."""

    year_min: int = 1901
    year_max: int = 9999
    query: str = ""
    categories: list[str] = field(default_factory=list)
    kinds: list[str] = field(default_factory=list)
    genders: list[str] = field(default_factory=list)
    birth_countries: list[str] = field(default_factory=list)
    birth_cities: list[str] = field(default_factory=list)
    continents: list[str] = field(default_factory=list)
    death_countries: list[str] = field(default_factory=list)
    work_countries: list[str] = field(default_factory=list)
    work_cities: list[str] = field(default_factory=list)
    institutions: list[str] = field(default_factory=list)
    statuses: list[str] = field(default_factory=list)
    age_min: int = 0
    age_max: int = 110
    include_unknown_age: bool = True
    repeated_only: bool = False
    with_coordinates: bool = False


class AnalyticsService:
    """Одинаковые фильтры и правила подсчёта для сайта и HTTP API."""

    def __init__(self, credits, affiliations, residences=None):
        """Сохранить таблицы награждений, аффилиаций и расположения."""
        self.credits = credits
        self.affiliations = affiliations
        self.residences = (
            residences
            if residences is not None
            else pd.DataFrame(
                columns=[
                    "award_key",
                    "ordinal",
                    "city_now",
                    "country_now",
                    "lat",
                    "lon",
                    "coord_source",
                ]
            )
        )

    def filter(self, spec):
        """Применить все условия как пересечение, сохраняя выбранные награждения."""
        df = self.credits
        mask = df.award_year.between(spec.year_min, spec.year_max)
        for col, values in [
            ("category", spec.categories),
            ("kind", spec.kinds),
            ("gender_label", spec.genders),
            ("origin_country", spec.birth_countries),
            ("origin_city", spec.birth_cities),
            ("origin_continent", spec.continents),
            ("death_country", spec.death_countries),
            ("prize_status", spec.statuses),
        ]:
            if values:
                mask &= df[col].isin(values)
        for token in fold(spec.query).split():
            mask &= df.search_text.str.contains(token, regex=False, na=False)
        mask &= df.award_age.between(spec.age_min, spec.age_max) | (
            df.award_age.isna() & spec.include_unknown_age
        )
        if spec.repeated_only:
            repeated = df.groupby("laureate_id").prize_key.nunique()
            mask &= df.laureate_id.isin(repeated[repeated > 1].index)
        if spec.with_coordinates:
            mask &= df.origin_lat.notna() & df.origin_lon.notna()
        if spec.work_countries or spec.work_cities or spec.institutions:
            a = self.locations(spec)
            mask &= df.award_key.isin(a.award_key)
        return df[mask].copy()

    def filter_affiliations(self, spec):
        """Проверить город, страну и учреждение в одной и той же аффилиации."""
        a = self.affiliations
        # All geography/institution conditions must match the SAME affiliation.
        for col, values in [
            ("country_now", spec.work_countries),
            ("city_now", spec.work_cities),
            ("name", spec.institutions),
        ]:
            if values:
                a = a[a[col].isin(values)]
        return a

    def locations(self, spec):
        """Работа людей и официальное расположение организаций — с разными подписями."""
        a = self.filter_affiliations(spec).rename(
            columns={
                "lat": "work_lat",
                "lon": "work_lon",
                "name": "institution",
                "city_now": "work_city",
                "country_now": "work_country",
                "coord_source": "work_coord_source",
            }
        )
        a = a.copy()
        a["destination_kind"] = "Работа при награждении"
        index = CityIndex.from_frames(self.credits, self.affiliations, self.residences)
        organizations = organization_locations(self.credits, self.residences, index)
        for column, values in [
            ("work_country", spec.work_countries),
            ("work_city", spec.work_cities),
            ("institution", spec.institutions),
        ]:
            if values:
                organizations = organizations[organizations[column].isin(values)]
        columns = [
            "award_key",
            "ordinal",
            "institution",
            "work_lat",
            "work_lon",
            "work_city",
            "work_country",
            "work_coord_source",
            "destination_kind",
        ]
        if organizations.empty:
            return a[columns]
        if a.empty:
            return organizations[columns]
        return pd.concat([a[columns], organizations[columns]], ignore_index=True)

    def routes(self, selected, spec, one_per_person=True):
        """Связать подтверждённые точки; отсутствие назначения не порождает маршрут."""
        merged = selected.merge(self.locations(spec), on="award_key")
        merged = merged.dropna(
            subset=["origin_lat", "origin_lon", "work_lat", "work_lon"]
        )
        merged = merged.sort_values(
            ["award_year", "ordinal", "prize_key"], ascending=[False, True, True]
        )
        if one_per_person:
            merged = merged.drop_duplicates("laureate_id")
        merged["distance_km"] = (
            merged.apply(
                lambda r: haversine(r.origin_lat, r.origin_lon, r.work_lat, r.work_lon),
                axis=1,
            )
            if len(merged)
            else pd.Series(dtype=float)
        )
        return merged


def haversine(lat1, lon1, lat2, lon2):
    """Вычислить расстояние по сфере в километрах, а не длину реального маршрута."""
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dlat, dlon = p2 - p1, math.radians(lon2 - lon1)
    a = math.sin(dlat / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlon / 2) ** 2
    return 6371.0088 * 2 * math.asin(math.sqrt(min(1, max(0, a))))


def great_circle(lat1, lon1, lat2, lon2, steps=32):
    """Построить дугу большого круга с разрывом при переходе через 180 градусов."""

    def vec(lat, lon):
        """Преобразовать широту и долготу в единичный трёхмерный вектор."""
        lat, lon = math.radians(lat), math.radians(lon)
        return (
            math.cos(lat) * math.cos(lon),
            math.cos(lat) * math.sin(lon),
            math.sin(lat),
        )

    u, v = vec(lat1, lon1), vec(lat2, lon2)
    omega = math.acos(min(1, max(-1, sum(a * b for a, b in zip(u, v)))))
    # Near coincident/antipodal endpoints have no uniquely stable interpolation.
    if abs(math.sin(omega)) < 1e-9:
        return [lat1, lat2], [lon1, lon2]
    lats, lons = [], []
    for t in range(steps + 1):
        w = t / steps
        xyz = [
            (math.sin((1 - w) * omega) * a + math.sin(w * omega) * b) / math.sin(omega)
            for a, b in zip(u, v)
        ]
        lat = math.degrees(math.atan2(xyz[2], math.hypot(xyz[0], xyz[1])))
        lon = math.degrees(math.atan2(xyz[1], xyz[0]))
        if lons and lons[-1] is not None and abs(lon - lons[-1]) > 180:
            lats.append(None)
            lons.append(None)
        lats.append(lat)
        lons.append(lon)
    return lats, lons


def csv_bytes(df):
    """Prevent spreadsheet formula execution in exports containing source text."""
    safe = df.copy()
    for col in safe.select_dtypes(include=["object", "string"]).columns:
        safe[col] = safe[col].map(
            lambda v: (
                "'" + v
                if isinstance(v, str) and v.lstrip().startswith(("=", "+", "-", "@"))
                else v
            )
        )
    return safe.to_csv(index=False).encode("utf-8-sig")
