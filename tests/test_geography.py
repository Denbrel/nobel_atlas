"""Регрессии карт: организации, неоднозначные города, категории и нулевой лимит."""

import json
from pathlib import Path
import sqlite3

from nobel import charts
from nobel.analysis import AnalyticsService, FilterSpec, prepare
from nobel.exports import read_laureates
from nobel.geography import CityIndex
from nobel.storage import DatabaseRepository

ROOT = Path(__file__).resolve().parents[1]


def real_service():
    """Локальный официальный снимок позволяет проверить реальные организации без сети."""
    repo = DatabaseRepository(ROOT / "nobel_database.sqlite")
    credits, affiliations, _ = repo.read_frames()
    residences = repo.read_residences()
    return AnalyticsService(
        prepare(credits, affiliations, residences=residences), affiliations, residences
    )


def test_city_index_requires_unique_city_and_country():
    index = CityIndex()
    index.add("City", "Country A", 0, 0)
    assert index.resolve("City", "Country A") == (0, 0)
    assert index.resolve("City", "Country B") is None
    index.add("City", "Country A", 10, 10)
    assert index.resolve("City", "Country A") is None


def test_organizations_have_origins_without_fake_births_or_destinations():
    service = real_service()
    spec = FilterSpec(kinds=["organization"])
    selected = service.filter(spec)
    assert selected.birth_lat.isna().all()  # Основание не записывается в поле рождения.
    figure, count = charts.birth_map(selected)
    assert count > 0
    assert sum(len(trace.lat) for trace in figure.data) == count
    assert all(trace.marker.color == charts.COLORS[trace.name] for trace in figure.data)
    routes = service.routes(selected, spec)
    assert "1043" in set(routes.laureate_id)  # Nihon Hidankyo: две разные точки API.
    assert "482" not in set(
        routes.laureate_id
    )  # ICRC: основание есть, маршрут не придумывается.
    unpaired = selected[~selected.laureate_id.isin(routes.laureate_id)]
    figure, shown, total = charts.flow_map(routes, 0, focus="1043", unpaired=unpaired)
    assert shown.empty and total > 0
    assert all(len(trace.lat) == 0 for trace in figure.data)
    figure, shown, total = charts.flow_map(routes, 10000, unpaired=unpaired)
    assert len(shown) == total
    assert any(
        trace.marker.symbol == "diamond-open"
        for trace in figure.data
        if trace.mode == "markers"
    )


def test_person_color_is_last_selected_category_and_deduplicated(repo):
    credits, affiliations, _ = repo.read_frames()
    selected = prepare(credits, affiliations)
    figure, count = charts.birth_map(selected)
    assert count == 1
    assert figure.data[0].name == "Химия"
    assert figure.data[0].marker.color == charts.COLORS["Химия"]
    assert "Физика" in figure.data[0].text[0]  # Другие премии не теряются в подсказке.


def test_presence_of_birth_date_is_not_exactness(repo):
    credits, affiliations, _ = repo.read_frames()
    quality = charts.coverage_table(
        prepare(credits, affiliations), affiliations
    ).set_index("Поле")
    assert quality.loc["Дата рождения: запись есть", "Доля, %"] == 100
    assert quality.loc["Дата рождения: точный день", "Доля, %"] == 50


def test_json_export_spans_multiple_batches_and_preserves_all_fields(repo):
    identifiers = [f"extra-{n:04}" for n in range(1100)]
    with sqlite3.connect(repo.path) as connection:
        for identifier in identifiers:
            raw = {
                "id": identifier,
                "futureField": {"ru": "Не терять", "values": [1, 2]},
            }
            connection.execute(
                "INSERT INTO laureates (id,name,kind,raw_json) VALUES (?,?,?,?)",
                (identifier, identifier, "person", json.dumps(raw)),
            )
    records = read_laureates(repo.path, identifiers + identifiers[:10])
    assert [row["id"] for row in records] == identifiers
    assert all(row["futureField"]["ru"] == "Не терять" for row in records)
    assert read_laureates(repo.path, []) == []
