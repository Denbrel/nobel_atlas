"""Автоматические проверки: фильтры, подсчёты и геодезия."""

from nobel.analysis import (
    prepare,
    AnalyticsService,
    FilterSpec,
    haversine,
    great_circle,
    csv_bytes,
)
from nobel import charts
import pandas as pd


def service(repo):
    df, a, p = repo.read_frames()
    return AnalyticsService(prepare(df, a), a)


def test_counts_and_missing_geo(repo):
    s = service(repo)
    df = s.filter(FilterSpec())
    assert len(df) == 4 and df.laureate_id.nunique() == 3
    assert len(s.filter(FilterSpec(query="Example"))) == 3
    assert len(s.filter(FilterSpec(query="[.*"))) == 0
    assert len(s.filter(FilterSpec(with_coordinates=True))) == 2
    assert len(s.filter(FilterSpec(repeated_only=True))) == 2
    assert len(s.filter(FilterSpec(kinds=["organization"]))) == 1
    assert len(s.filter(FilterSpec(include_unknown_age=False))) == 3


def test_filters_match_same_affiliation(repo):
    s = service(repo)
    assert s.filter(FilterSpec(work_countries=["UK"], work_cities=["Stockholm"])).empty
    assert len(s.filter(FilterSpec(work_countries=["UK"], work_cities=["London"]))) == 1


def test_routes_keep_all_affiliations_and_control_one_per_person(repo):
    s = service(repo)
    df = s.filter(FilterSpec())
    assert len(s.routes(df, FilterSpec(), False)) == 3
    routes = s.routes(df, FilterSpec(), True)
    assert len(routes) == 1 and routes.iloc[0].work_city == "New York"
    spec = FilterSpec(work_countries=["Sweden"])
    assert s.routes(s.filter(spec), spec).iloc[0].work_city == "Stockholm"


def test_great_circle_and_distance():
    assert haversine(0, 0, 0, 0) == 0
    assert abs(haversine(0, 0, 0, 180) - 20015.11) < 1
    lat, lon = great_circle(30, 170, 35, -170)
    assert None in lon and abs(lat[0] - 30) < 1e-8 and abs(lon[-1] + 170) < 1e-8
    for i in range(1, len(lon)):
        if lon[i] is not None and lon[i - 1] is not None:
            assert abs(lon[i] - lon[i - 1]) <= 180


def test_aggregate_figures_deduplicate(repo):
    s = service(repo)
    df = s.filter(FilterSpec())
    f = charts.money(df, False)
    assert sum(len(t.x) for t in f.data) == 3
    f = charts.countries(df)
    assert sum(f.data[0].x) == 1
    fig, shown, total = charts.flow_map(s.routes(df, FilterSpec()), limit=10)
    assert total == 1 and len(shown) == 1 and fig.data[2].marker.symbol == "star"


def test_csv_escaping():
    data = csv_bytes(pd.DataFrame({"name": ["=SUM(1,2)", " @evil", "normal"]})).decode(
        "utf-8-sig"
    )
    assert "'=SUM" in data and "' @evil" in data
