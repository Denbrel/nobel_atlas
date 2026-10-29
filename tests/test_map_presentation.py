"""Подсказки карт: известные места, отсутствие выдуманных событий и фильтры."""

import re

import pandas as pd
import pytest

from nobel import charts
from nobel.analysis import AnalyticsService, FilterSpec, prepare


@pytest.fixture
def map_data(repo):
    """Синтетические награждения с несколькими местами работы и местом смерти."""
    credits, affiliations, _ = repo.read_frames()
    selected = prepare(credits, affiliations)
    person = selected.laureate_id == "1"
    selected.loc[person, "name"] = "Alice <Example>"
    selected.loc[person, "death_date"] = "2025-03-12"
    selected.loc[person, "death_city"] = "Paris"
    selected.loc[person, "death_country"] = "France"
    selected.loc[person, "death_lat"] = 48.85
    selected.loc[person, "death_lon"] = 2.35
    service = AnalyticsService(selected, affiliations)
    return selected, service.locations(FilterSpec()), service


def plain_tooltip(text):
    """Убрать только нашу разметку для проверки текста независимо от переносов."""
    return re.sub(r"<[^>]+>", "", text.replace("<br>", " "))


def test_details_keep_known_places_without_coordinates_and_respect_selection(map_data):
    """Место без координат остаётся в карточке, но чужие премии туда не попадают."""
    selected, locations, _ = map_data
    locations.loc[locations.work_city == "London", ["work_lat", "work_lon"]] = float("nan")
    original = selected.copy(deep=True)
    enriched = charts.map_details(selected, locations)
    pd.testing.assert_frame_equal(selected, original)
    assert enriched.award_key.tolist() == selected.award_key.tolist()
    for label in enriched.loc[enriched.laureate_id == "1", "map_work_places"]:
        assert all(city in label for city in ("London", "Stockholm", "New York"))
    chemistry = charts.map_details(selected[selected.award_year == 2010], locations)
    assert "New York" in chemistry.iloc[0].map_work_places
    assert "London" not in chemistry.iloc[0].map_work_places
    missing = charts.map_details(selected, locations.iloc[:0])
    assert missing.map_work_places.eq("Не указано").all()


@pytest.mark.parametrize("mode", ["birth", "death", "work", "flow"])
def test_every_marker_card_has_all_three_events_without_source_labels(map_data, mode):
    """Проверяем карточку каждой разновидности карты, включая обе точки связи."""
    selected, locations, service = map_data
    selected = selected[selected.laureate_id == "1"]
    details = charts.map_details(selected, locations)
    if mode in ("birth", "death"):
        figure, _ = charts.birth_map(details, mode=mode)
    elif mode == "work":
        figure = charts.work_map(locations.merge(details, on="award_key"))
    else:
        figure, _, _ = charts.flow_map(service.routes(details, FilterSpec()))
    tooltips = [text for trace in figure.data if trace.text is not None for text in trace.text]
    assert tooltips
    for text in tooltips:
        plain = plain_tooltip(text)
        assert "Alice &lt;Example&gt;" in text and "<Example>" not in text
        assert all(label in plain for label in ("Рождение:", "Работа / расположение:", "Место смерти:"))
        assert all(place in plain for place in ("Zero", "London", "Stockholm", "New York", "Paris"))
        assert "2025-03-12" in plain
        assert "Nobel API" not in text and "Координаты:" not in text


@pytest.mark.parametrize("with_coordinates", [True, False])
def test_organization_cards_show_founding_and_known_location_without_fake_death(map_data, with_coordinates):
    """Основание организации не становится рождением; одиночная точка тоже информативна."""
    selected, locations, service = map_data
    selected = selected[selected.kind == "organization"].copy()
    selected["origin_city"], selected["origin_country"] = "Tokyo", "Japan"
    selected["origin_lat"], selected["origin_lon"] = 35.68, 139.69
    destination = pd.DataFrame([{
        "award_key": selected.iloc[0].award_key, "ordinal": 0,
        "institution": "Расположение организации · Nobel API",
        "work_lat": 34.39 if with_coordinates else float("nan"),
        "work_lon": 132.46 if with_coordinates else float("nan"),
        "work_city": "Hiroshima", "work_country": "Japan",
        "work_coord_source": "Nobel API: совпадение города и страны",
        "destination_kind": "Расположение организации",
    }])
    details = charts.map_details(selected, destination)
    routes = details.merge(destination, on="award_key").dropna(subset=["work_lat", "work_lon"])
    routes["distance_km"] = 680.0
    unpaired = details[~details.laureate_id.isin(routes.laureate_id)]
    figure, _, _ = charts.flow_map(routes, unpaired=unpaired)
    tooltips = [text for trace in figure.data if trace.text is not None for text in trace.text]
    assert tooltips
    for text in tooltips:
        plain = plain_tooltip(text)
        assert "Основание:" in plain and "1995 (год)" in plain
        assert "Tokyo" in plain and "Hiroshima" in plain
        assert "Неприменимо к организации" in plain
        assert "Nobel API" not in text and "Рождение:" not in plain
