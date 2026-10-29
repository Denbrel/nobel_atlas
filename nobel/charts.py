"""Графики Plotly: единая палитра и явно определённые единицы подсчёта."""

from html import escape
import numpy as np
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from .models import CATEGORIES
from .analysis import great_circle

COLORS = {v[1]: v[2] for v in CATEGORIES.values()}
INK, TEAL, GOLD = "#213E49", "#287D80", "#B68A3A"


def style(fig, height=340, geo=False):
    """Задать общую типографику, сетку, отступы и легенду графика."""
    fig.update_layout(
        template="plotly_white",
        height=height,
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        font=dict(family="Arial, sans-serif", color=INK, size=12),
        margin=dict(l=12, r=12, t=15, b=25),
        legend=dict(title=None, orientation="h", y=-0.18, x=0),
        hoverlabel=dict(bgcolor="#FFFFFF", font_size=12),
    )
    if not geo:
        fig.update_xaxes(gridcolor="#E9EDEA", zeroline=False)
        fig.update_yaxes(gridcolor="#E9EDEA", zeroline=False)
    return fig


def map_style(fig, projection="natural earth", height=450):
    """Оформить географическую подложку и выбрать проекцию карты."""
    style(fig, height, geo=True)
    # При смене фильтров сохраняем ручной масштаб; смена проекции сбрасывает его.
    fig.update_layout(uirevision=f"map-{projection}")
    fig.update_geos(
        projection_type=projection,
        resolution=110,
        showframe=False,
        showcountries=True,
        countrycolor="#D0DAD7",
        countrywidth=0.5,
        showcoastlines=True,
        coastlinecolor="#C1CECC",
        coastlinewidth=0.5,
        showland=True,
        landcolor="#EEF1EA",
        showocean=True,
        oceancolor="#F8FAF7",
        bgcolor="rgba(0,0,0,0)",
        lataxis_range=[-60, 85],
    )
    return fig


def origin_points(df):
    """Один маркер на лауреата; цвет последней выбранной премии, все категории в подсказке."""
    base = (
        df.sort_values(["award_year", "prize_key"], ascending=[False, True])
        .drop_duplicates("laureate_id")
        .copy()
    )
    categories = df.groupby("laureate_id").category_label.agg(
        lambda v: ", ".join(sorted(set(v)))
    )
    years = df.groupby("laureate_id").award_year.agg(
        lambda v: ", ".join(map(str, sorted(set(v))))
    )
    base["categories"] = base.laureate_id.map(categories)
    base["years"] = base.laureate_id.map(years)
    return base


def birth_map(df, mode="birth", projection="natural earth", size=7):
    """Карта происхождения (рождение/основание) или смерти с единой палитрой категорий."""
    base = origin_points(df)
    prefix = "origin" if mode == "birth" else "death"
    base = base.dropna(subset=[prefix + "_lat", prefix + "_lon"])
    fig = go.Figure()
    for category, group in base.groupby("category_label", sort=True):
        hover = []
        for _, row in group.iterrows():
            kind = row["origin_kind"] if mode == "birth" else "Место смерти"
            source = row.get(prefix + "_coord_source", "Nobel API") or "Nobel API"
            hover.append(
                f'<b>{escape(row["name"])}</b><br>{kind}: {escape(row[prefix+"_city"])}, {escape(row[prefix+"_country"])}<br>{escape(row["categories"])} · {row["years"]}<br>Координаты: {escape(source)}'
            )
        fig.add_trace(
            go.Scattergeo(
                lat=group[prefix + "_lat"],
                lon=group[prefix + "_lon"],
                mode="markers",
                marker=dict(
                    size=size,
                    color=COLORS.get(category, TEAL),
                    opacity=0.78,
                    symbol=[
                        "diamond" if k == "organization" else "circle"
                        for k in group.kind
                    ],
                    line=dict(width=0.6, color="#FFFFFF"),
                ),
                text=hover,
                hovertemplate="%{text}<extra></extra>",
                name=category,
                legendgroup=category,
            )
        )
    return map_style(fig, projection), len(base)


def work_map(routes, projection="natural earth", size=7):
    """Звёзды обозначают аффилиацию людей или расположение организаций из API."""
    fig = go.Figure()
    for category, group in routes.groupby("category_label", sort=True):
        fig.add_trace(
            go.Scattergeo(
                lat=group.work_lat,
                lon=group.work_lon,
                mode="markers",
                marker=dict(
                    symbol="star",
                    size=size + 2,
                    color=COLORS.get(category, GOLD),
                    opacity=0.8,
                ),
                text=[
                    f'<b>{escape(r["name"])}</b><br>{escape(r["destination_kind"])}: {escape(r["work_city"])}<br>{escape(r["institution"])} · {int(r["award_year"])}<br>Координаты: {escape(r["work_coord_source"] or "Nobel API")}'
                    for _, r in group.iterrows()
                ],
                hovertemplate="%{text}<extra></extra>",
                name=category,
                legendgroup=category,
            )
        )
    return map_style(fig, projection)


def trend(df, step=10):
    """Показать динамику награждений; отсутствующие периоды заполнить нулями."""
    d = df.assign(period=(df.award_year // step) * step)
    grouped = (
        d.groupby(["period", "category_label"]).size().rename("count").reset_index()
    )
    if len(grouped):
        index = pd.MultiIndex.from_product(
            [
                range(
                    int(grouped.period.min()), int(grouped.period.max()) + step, step
                ),
                sorted(df.category_label.unique()),
            ],
            names=["period", "category_label"],
        )
        grouped = (
            grouped.set_index(["period", "category_label"])
            .reindex(index, fill_value=0)
            .reset_index()
        )
    fig = px.area(
        grouped,
        x="period",
        y="count",
        color="category_label",
        color_discrete_map=COLORS,
        labels={
            "period": "Год" if step == 1 else "Начало десятилетия",
            "count": "Награждения",
            "category_label": "Категория",
        },
    )
    return style(fig)


def categories(df):
    """Сравнить число награждений по категориям в общей палитре."""
    d = df.groupby("category_label").size().sort_values().rename("count").reset_index()
    fig = px.bar(
        d,
        y="category_label",
        x="count",
        color="category_label",
        color_discrete_map=COLORS,
        orientation="h",
        text="count",
        labels={"category_label": "", "count": "Награждения"},
    )
    fig.update_layout(showlegend=False)
    fig.update_traces(textposition="outside", cliponaxis=False)
    return style(fig)


def ages(df, bins=20, split=False):
    """Построить гистограмму возраста людей или срока существования организаций."""
    org_only = df.kind.eq("organization").all()
    age_column = "organization_age" if org_only else "award_age"
    d = (df if org_only else df[df.kind == "person"]).dropna(subset=[age_column])
    fig = px.histogram(
        d,
        x=age_column,
        color="category_label" if split else None,
        nbins=bins,
        color_discrete_map=COLORS,
        color_discrete_sequence=[TEAL],
        labels={
            age_column: (
                "Лет от основания до премии"
                if org_only
                else "Возраст на дату присуждения"
            ),
            "category_label": "Категория",
        },
        barmode="stack",
    )
    fig.update_layout(yaxis_title="Награждения")
    return style(fig)


def countries(df, top=12, historical=False):
    """Посчитать уникальных лауреатов по стране рождения либо основания."""
    org_only = df.kind.eq("organization").all()
    col = (
        "origin_country"
        if org_only
        else ("birth_country_historical" if historical else "birth_country")
    )
    d = (df if org_only else df[df.kind == "person"]).drop_duplicates("laureate_id")
    d = (
        d[d[col] != "Не указано"]
        .groupby(col)
        .size()
        .nlargest(top)
        .sort_values()
        .rename("count")
        .reset_index()
    )
    fig = px.bar(
        d,
        x="count",
        y=col,
        orientation="h",
        text="count",
        color_discrete_sequence=[TEAL],
        labels={"count": "Уникальные лауреаты", col: ""},
    )
    return style(fig)


def gender(df, percent=True):
    """Показать награждения людей по полу: абсолютные числа или доли."""
    d = (
        df[df.kind == "person"]
        .groupby(["decade", "gender_label"])
        .size()
        .rename("count")
        .reset_index()
    )
    d["percent"] = 100 * d["count"] / d.groupby("decade")["count"].transform("sum")
    fig = px.bar(
        d,
        x="decade",
        y="percent" if percent else "count",
        color="gender_label",
        color_discrete_map={
            "Мужчины": "#73999F",
            "Женщины": "#B68A3A",
            "Не указано": "#B4B9B5",
        },
        labels={
            "decade": "Десятилетие",
            "percent": "Доля награждений, %",
            "count": "Награждения",
            "gender_label": "Пол",
        },
    )
    return style(fig)


def heatmap(df):
    """Сопоставить категории и десятилетия через таблицу частот."""
    data = pd.crosstab(df.category_label, df.decade)
    fig = px.imshow(
        data,
        aspect="auto",
        text_auto=True,
        color_continuous_scale=["#F3F5EF", "#93BBB2", "#236E73"],
        labels={"x": "Десятилетие", "y": "Категория", "color": "Награждения"},
    )
    fig.update_layout(coloraxis_showscale=False)
    return style(fig)


def institutions(df, affiliations, top=15):
    """Посчитать человека один раз в каждом учреждении; итоги не складываются."""
    a = affiliations[affiliations.award_key.isin(df.award_key)].merge(
        df[["award_key", "laureate_id"]], on="award_key"
    )
    # One laureate counts once in each institution; these counts are not additive.
    d = (
        a.groupby("name")
        .laureate_id.nunique()
        .nlargest(top)
        .sort_values()
        .rename("count")
        .reset_index()
    )
    fig = px.bar(
        d,
        x="count",
        y="name",
        orientation="h",
        color_discrete_sequence=[TEAL],
        labels={"count": "Уникальные лауреаты в организации", "name": ""},
    )
    return style(fig, max(350, top * 26))


def money(df, adjusted=True):
    """Показать сумму на премию, исключив дубли от нескольких получателей."""
    d = df.drop_duplicates("prize_key").sort_values("award_year").copy()
    col = "prize_amount_adjusted" if adjusted else "prize_amount"
    d["million"] = d[col] / 1e6
    fig = px.line(
        d,
        x="award_year",
        y="million",
        color="category_label",
        color_discrete_map=COLORS,
        labels={
            "award_year": "Год",
            "million": "Сумма премии, млн SEK",
            "category_label": "Категория",
        },
    )
    return style(fig)


def flow_map(
    routes,
    limit=60,
    opacity=0.24,
    projection="natural earth",
    focus=None,
    unpaired=None,
):
    """Дуги между известными точками; одиночные основания не становятся маршрутами.

    Лимит 0 запрещает связи, в том числе при выбранном фокусе. Нулевые расстояния
    сохраняют маркеры, но не получают невидимую «миграционную» дугу.
    """
    eligible = routes.copy()
    selected = eligible[eligible.laureate_id == focus] if focus else eligible
    shown = selected.sample(
        n=min(max(0, int(limit)), len(selected)), random_state=42
    ).sort_values("name")
    fig = go.Figure()
    lats, lons = [], []
    for row in shown.itertuples():
        if row.distance_km <= 1:
            continue
        lat, lon = great_circle(
            row.origin_lat, row.origin_lon, row.work_lat, row.work_lon
        )
        lats += lat + [None]
        lons += lon + [None]
    fig.add_trace(
        go.Scattergeo(
            lat=lats,
            lon=lons,
            mode="lines",
            line=dict(
                color=f"rgba(66,116,125,{opacity})", width=1.1 if not focus else 2.2
            ),
            hoverinfo="skip",
            name="Связь между местами",
            showlegend=False,
        )
    )
    for category, group in shown.groupby("category_label", sort=True):
        hover = [
            f'<b>{escape(r["name"])}</b><br>{escape(r["origin_kind"])}: {escape(r["origin_city"])} → {escape(r["destination_kind"])}: {escape(r["work_city"])}<br>{int(r["award_year"])} · {r["distance_km"]:,.0f} км<br>Начало: {escape(r["origin_coord_source"] or "Nobel API")}<br>Назначение: {escape(r["work_coord_source"] or "Nobel API")}'
            for _, r in group.iterrows()
        ]
        for prefix, size in [("origin", 7), ("work", 10)]:
            symbols = (
                ["diamond" if k == "organization" else "circle" for k in group.kind]
                if prefix == "origin"
                else "star"
            )
            fig.add_trace(
                go.Scattergeo(
                    lat=group[prefix + "_lat"],
                    lon=group[prefix + "_lon"],
                    mode="markers",
                    marker=dict(
                        symbol=symbols,
                        color=COLORS.get(category, TEAL),
                        size=size,
                        opacity=0.85,
                        line=dict(width=0.6, color="#FFFFFF"),
                    ),
                    text=hover,
                    hovertemplate="%{text}<extra></extra>",
                    name=category,
                    legendgroup=category,
                    showlegend=prefix == "origin",
                )
            )
    if unpaired is not None:
        single = origin_points(unpaired).dropna(subset=["origin_lat", "origin_lon"])
        if focus:
            single = single[single.laureate_id == focus]
        for category, group in single.groupby("category_label", sort=True):
            fig.add_trace(
                go.Scattergeo(
                    lat=group.origin_lat,
                    lon=group.origin_lon,
                    mode="markers",
                    marker=dict(
                        symbol="diamond-open", size=9, color=COLORS.get(category, TEAL)
                    ),
                    text=[
                        f'<b>{escape(r["name"])}</b><br>Основание: {escape(r["origin_city"])}<br>Второе место с координатами не указано<br>{escape(r["origin_coord_source"])}'
                        for _, r in group.iterrows()
                    ],
                    hovertemplate="%{text}<extra></extra>",
                    name=category,
                    legendgroup=category,
                    showlegend=category not in set(shown.category_label),
                )
            )
    return map_style(fig, projection, 510), shown, len(eligible)


def sankey(routes, top=18):
    """Сгруппировать пары стран происхождения и назначения; выбрать крупные потоки."""
    d = routes[
        (routes.origin_country != "Не указано") & (routes.work_country != "")
    ].rename(
        columns={
            "birth_country": "person_birth_country",
            "origin_country": "birth_country",
        }
    )
    counts = (
        d.groupby(["birth_country", "work_country"])
        .size()
        .nlargest(top)
        .reset_index(name="count")
    )
    origins = sorted(counts.birth_country.unique())
    destinations = sorted(counts.work_country.unique())
    labels = origins + destinations
    fig = go.Figure(
        go.Sankey(
            arrangement="snap",
            node=dict(
                pad=18,
                thickness=13,
                label=labels,
                color=["#6F9EA4"] * len(origins) + ["#C3A05F"] * len(destinations),
            ),
            link=dict(
                source=[origins.index(x) for x in counts.birth_country],
                target=[
                    len(origins) + destinations.index(x) for x in counts.work_country
                ],
                value=counts["count"],
                color="rgba(103,147,150,.22)",
                hovertemplate="%{source.label} → %{target.label}: %{value}<extra></extra>",
            ),
        )
    )
    return style(fig, 430), int(counts["count"].sum())


def coverage_table(df, affiliations):
    """Отдельные знаменатели для наличия даты, её точности и координат организаций."""
    people = df[df.kind == "person"].drop_duplicates("laureate_id")
    organizations = df[df.kind == "organization"].drop_duplicates("laureate_id")
    awards = df[df.kind == "person"]
    with_work = set(affiliations.dropna(subset=["lat", "lon"]).award_key)
    rows = []

    def add(label, flags, unit):
        """Сохранить числитель, знаменатель и долю; пустой знаменатель даёт None."""
        total = len(flags)
        known = int(flags.fillna(False).sum())
        rows.append(
            {
                "Поле": label,
                "Заполнено": known,
                "Всего": total,
                "Доля, %": 100 * known / total if total else None,
                "Единица": unit,
            }
        )

    add(
        "Дата рождения: запись есть",
        people.birth_date.notna() & people.birth_date.ne(""),
        "Люди",
    )
    add("Дата рождения: точный день", people.birth_date_exact, "Люди")
    add(
        "Координаты рождения",
        people.origin_lat.notna() & people.origin_lon.notna(),
        "Люди",
    )
    add("Точный возраст при премии", awards.age_basis.eq("exact"), "Награждения людей")
    add("Координаты работы", awards.award_key.isin(with_work), "Награждения людей")
    add(
        "Место основания: город известен",
        organizations.origin_city.ne("Не указано"),
        "Организации",
    )
    add(
        "Координаты основания",
        organizations.origin_lat.notna() & organizations.origin_lon.notna(),
        "Организации",
    )
    return pd.DataFrame(rows)


def coverage(df, affiliations):
    """Неприменимые показатели исключаются, а не изображаются как нулевая полнота."""
    data = coverage_table(df, affiliations)
    data = data[data["Всего"] > 0]
    fig = go.Figure(
        go.Bar(
            x=data["Доля, %"],
            y=data["Поле"],
            orientation="h",
            customdata=data[["Заполнено", "Всего", "Единица"]],
            marker_color=TEAL,
            texttemplate="%{x:.1f}%",
            textposition="auto",
            hovertemplate="%{y}: %{customdata[0]} из %{customdata[1]}<br>%{customdata[2]}<extra></extra>",
        )
    )
    fig.update_xaxes(range=[0, 100], title="Заполненность, %")
    return style(fig, max(260, len(data) * 42))


def repeat_awards(df):
    """Распределение организаций по числу премий в выбранном срезе."""
    counts = df.groupby("laureate_id").prize_key.nunique().value_counts().sort_index()
    fig = go.Figure(
        go.Bar(
            x=[str(int(n)) for n in counts.index],
            y=counts.values,
            marker_color=GOLD,
            text=counts.values,
            textposition="auto",
        )
    )
    fig.update_layout(
        xaxis_title="Награждений на организацию", yaxis_title="Организаций"
    )
    return style(fig)
