"""География людей и организаций без подмены отсутствующих мест.

Рождение и основание остаются разными полями. Для общей карты используется
отдельная группа origin_*. Недостающие координаты можно перенести из другой
записи Nobel только при точном совпадении города и страны и отсутствии
конфликтующих координат. Это производное значение с отдельным источником.
"""

from collections import defaultdict
import pandas as pd


class CityIndex:
    """Локальный справочник городов из уже загруженных официальных записей."""

    def __init__(self):
        """Создать набор кандидатов координат для каждого города и страны."""
        self.points = defaultdict(set)

    def add(self, city, country, lat, lon):
        """Запомнить координаты только для полного ключа «город + страна»."""
        if (
            city
            and country
            and city != "Не указано"
            and country != "Не указано"
            and pd.notna(lat)
            and pd.notna(lon)
        ):
            self.points[(city, country)].add((float(lat), float(lon)))

    def resolve(self, city, country):
        """Не выбирать произвольно, если у одинакового названия несколько точек."""
        points = self.points.get((city, country), set())
        return next(iter(points)) if len(points) == 1 else None

    @classmethod
    def from_frames(cls, credits, affiliations, residences=None):
        """Собрать индекс до фильтрации: выбор посетителя не влияет на координаты."""
        index = cls()
        for prefix in ("birth", "death", "founded"):
            fields = [f"{prefix}_{x}" for x in ("city", "country", "lat", "lon")]
            if set(fields) <= set(credits):
                for values in credits[fields].itertuples(index=False, name=None):
                    index.add(*values)
        for places in (affiliations, residences):
            if places is not None:
                for values in places[
                    ["city_now", "country_now", "lat", "lon"]
                ].itertuples(index=False, name=None):
                    index.add(*values)
        return index

    def fill(self, frame, prefix):
        """Дополнить копию таблицы; исходный JSON и официальная SQLite не меняются."""
        result = frame.copy()
        for row in result.index:
            lat, lon = result.at[row, prefix + "lat"], result.at[row, prefix + "lon"]
            if pd.notna(lat) and pd.notna(lon):
                continue
            point = self.resolve(
                result.at[row, prefix + "city"], result.at[row, prefix + "country"]
            )
            if point:
                result.loc[row, [prefix + "lat", prefix + "lon"]] = point
                result.at[row, prefix + "coord_source"] = (
                    "Nobel API: совпадение города и страны"
                )
        return result


def add_origins(credits, affiliations, residences=None):
    """Добавить общую точку происхождения, сохранив отдельно birth_ и founded_."""
    result = credits.copy()
    organizations = result.kind.eq("organization")
    for field in ("city", "country", "continent", "lat", "lon", "coord_source"):
        result["origin_" + field] = result["birth_" + field]
        if "founded_" + field in result:
            values = result["founded_" + field]
            if field in ("lat", "lon"):
                values = pd.to_numeric(values, errors="coerce")
            result.loc[organizations, "origin_" + field] = values.loc[organizations]
    result["origin_kind"] = organizations.map({True: "Основание", False: "Рождение"})
    return CityIndex.from_frames(credits, affiliations, residences).fill(
        result, "origin_"
    )


def organization_locations(credits, residences, index):
    """Места расположения организаций из residences, без догадок о штаб-квартире."""
    organizations = credits[credits.kind.eq("organization")]
    rows = residences[residences.award_key.isin(organizations.award_key)].copy()
    rows = rows.rename(
        columns={
            "city_now": "work_city",
            "country_now": "work_country",
            "lat": "work_lat",
            "lon": "work_lon",
            "coord_source": "work_coord_source",
        }
    )
    rows = index.fill(rows, "work_")
    rows["institution"] = "Расположение организации · Nobel API"
    rows["destination_kind"] = "Расположение организации"
    return rows
