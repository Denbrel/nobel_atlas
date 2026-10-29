"""Вход Streamlit: кэш SQLite, боковые фильтры, вкладки и композиция страницы."""

from pathlib import Path
import json
import os
import sqlite3
import pandas as pd
import plotly.express as px
import streamlit as st
from nobel.storage import DatabaseRepository
from nobel.analysis import FilterSpec, AnalyticsService, prepare, csv_bytes, UNKNOWN
from nobel.models import CATEGORIES
from nobel import charts
from nobel.ui import CSS, chart, render_card, render_footer
from nobel.exports import read_laureates
from nobel.models import full_date

st.set_page_config(
    page_title="Nobel Atlas · люди, открытия, места", page_icon="✦", layout="wide"
)
st.markdown(CSS, unsafe_allow_html=True)
DB = Path(os.getenv("NOBEL_DB", Path(__file__).with_name("nobel_database.sqlite")))


@st.cache_data(show_spinner=False)
def load_data(path, stamp):
    """Прочитать снимок один раз; stamp сбрасывает кэш при замене SQLite."""
    repo = DatabaseRepository(path)
    credits, affiliations, prizes = repo.read_frames()
    cache = repo.wikidata_cache()
    residences = repo.read_residences()
    return (
        prepare(credits, affiliations, cache, residences),
        affiliations,
        prizes,
        repo.metadata(),
        cache,
        residences,
    )


@st.cache_data(show_spinner=False)
def load_person(path, stamp, identifier):
    """Кэшировать полную запись одного лауреата для карточки."""
    return DatabaseRepository(path).raw_laureate(identifier)


if not DB.exists():
    st.error(
        "База данных не найдена. Загрузите nobel_database.sqlite из пакета проекта или выполните python updater.py."
    )
    st.stop()
try:
    stamp = (DB.stat().st_mtime_ns, DB.stat().st_size)
    df, affiliations, prizes, meta, cache, residences = load_data(str(DB), stamp)
except (sqlite3.Error, KeyError, ValueError) as exc:
    st.error(
        "Нужна база формата Nobel Atlas 2. Запустите python updater.py для безопасного обновления."
    )
    st.stop()
if df.empty:
    st.info("В базе пока нет награждений. Запустите обновление данных.")
    st.stop()
service = AnalyticsService(df, affiliations, residences)


def options(data, column):
    """Получить отсортированные непустые значения для фильтра."""
    return sorted(x for x in data[column].dropna().unique() if x != "")


def reset_filters():
    """Сбросить только фильтры, не затрагивая остальные настройки сеанса."""
    for key in list(st.session_state):
        if key.startswith("flt_"):
            del st.session_state[key]


with st.sidebar:
    st.markdown("### ✦ NOBEL ATLAS")
    st.caption("Настройте свой исследовательский срез")
    st.button("Сбросить фильтры", on_click=reset_filters, width="stretch")
    query = st.text_input(
        "Поиск по имени, мотивации и организации",
        placeholder="Например: Curie или quantum",
        key="flt_query",
    )
    low, high = int(df.award_year.min()), int(df.award_year.max())
    years = (
        st.slider("Год премии", low, high, (low, high), key="flt_years")
        if low < high
        else (low, high)
    )
    cats = st.multiselect(
        "Категории",
        options(df, "category"),
        format_func=lambda x: CATEGORIES.get(x, ("", x))[1],
        key="flt_cats",
        placeholder="Все категории",
    )
    kinds = st.multiselect(
        "Тип лауреата",
        ["person", "organization"],
        format_func=lambda x: {"person": "Люди", "organization": "Организации"}[x],
        key="flt_kinds",
        placeholder="Люди и организации",
    )
    genders = st.multiselect(
        "Пол / тип", options(df, "gender_label"), key="flt_gender", placeholder="Все"
    )
    with st.expander("Рождение / основание", expanded=True):
        birth_countries = st.multiselect(
            "Страна рождения / основания",
            options(df, "origin_country"),
            key="flt_birth_country",
        )
        birth_cities = st.multiselect(
            "Город рождения / основания",
            options(
                df[df.origin_country.isin(birth_countries)] if birth_countries else df,
                "origin_city",
            ),
            key="flt_birth_city",
        )
        continents = st.multiselect(
            "Континент", options(df, "origin_continent"), key="flt_continent"
        )
    with st.expander("Работа при награждении"):
        work_countries = st.multiselect(
            "Страна работы",
            options(affiliations, "country_now"),
            key="flt_work_country",
        )
        af = (
            affiliations[affiliations.country_now.isin(work_countries)]
            if work_countries
            else affiliations
        )
        work_cities = st.multiselect(
            "Город работы", options(af, "city_now"), key="flt_work_city"
        )
        if work_cities:
            af = af[af.city_now.isin(work_cities)]
        institutions = st.multiselect(
            "Университет / организация", options(af, "name"), key="flt_institution"
        )
    with st.expander("Возраст и дополнительные условия"):
        age = st.slider("Возраст при присуждении", 0, 110, (0, 110), key="flt_age")
        include_unknown = st.checkbox(
            "Включать неизвестный возраст и организации", True, key="flt_unknown_age"
        )
        repeated = st.checkbox("Только многократные лауреаты", key="flt_repeated")
        geo_only = st.checkbox("Есть координаты рождения / основания", key="flt_geo")
        death_countries = st.multiselect(
            "Страна смерти", options(df, "death_country"), key="flt_death_country"
        )
        statuses = st.multiselect(
            "Статус премии в API", options(df, "prize_status"), key="flt_status"
        )
    st.caption(
        "Пустой список означает «все». Фильтры действуют на все вкладки. Названия мест сохранены на языке API."
    )
spec = FilterSpec(
    year_min=years[0],
    year_max=years[1],
    query=query,
    categories=cats,
    kinds=kinds,
    genders=genders,
    birth_countries=birth_countries,
    birth_cities=birth_cities,
    continents=continents,
    work_countries=work_countries,
    work_cities=work_cities,
    institutions=institutions,
    death_countries=death_countries,
    statuses=statuses,
    age_min=age[0],
    age_max=age[1],
    include_unknown_age=include_unknown,
    repeated_only=repeated,
    with_coordinates=geo_only,
)
filtered = service.filter(spec)
# Компактный заголовок оставляет карту на первом экране.
st.markdown(
    '<div class="brand">✦ Nobel Atlas <span>Люди · открытия · места</span></div>',
    unsafe_allow_html=True,
)
if filtered.empty:
    st.info(
        "Для этой комбинации фильтров ничего не найдено. Измените параметры или нажмите «Сбросить фильтры»."
    )
    render_footer(meta)
    st.stop()

main, catalog, lab, about = st.tabs(
    ["Обзор", "Лауреаты", "Лаборатория", "О данных"], key="main_tabs", on_change="rerun"
)
if main.open:
    with main:
        st.markdown(
            '<div class="section-kicker">01 / ГЕОГРАФИЯ</div>', unsafe_allow_html=True
        )
        st.subheader("География лауреатов")
        m1, m2, m3 = st.columns([2, 1, 1])
        mode = m1.selectbox(
            "Что показать на карте",
            ["Рождение / основание", "Работа / расположение", "Места смерти"],
            key="map_mode",
        )
        projection_label = m2.selectbox(
            "Проекция", ["Мир", "Глобус"], key="map_projection"
        )
        projection = "natural earth" if projection_label == "Мир" else "orthographic"
        dot_size = m3.slider("Размер точек", 4, 14, 7, key="map_size")
        if mode == "Работа / расположение":
            map_af = service.locations(spec).merge(
                filtered[["award_key", "name", "award_year", "category_label", "kind"]],
                on="award_key",
            )
            map_af = map_af.dropna(subset=["work_lat", "work_lon"])
            chart(charts.work_map(map_af, projection, dot_size), "map_work")
            st.caption(
                f"★ Работа людей / расположение организаций из API · {len(map_af)} записей с координатами. Один лауреат может иметь несколько мест."
            )
            if map_af.empty:
                st.info(
                    "Для выбранных лауреатов здесь нет координат. Места основания организаций доступны в режиме «Рождение / основание»."
                )
        else:
            fig, n = charts.birth_map(
                filtered,
                "birth" if mode == "Рождение / основание" else "death",
                projection,
                dot_size,
            )
            chart(fig, "map_people")
            st.caption(
                f"● Человек · ◆ Основание организации · нанесено {n} из {filtered.laureate_id.nunique()} лауреатов. Цвет — категория последней выбранной премии; все категории и годы доступны при наведении."
            )
            if not n:
                st.info(
                    "Для этого режима и набора фильтров координаты отсутствуют. К организациям место смерти неприменимо."
                )
        st.caption(
            "Колесо мыши — масштаб · перетаскивание — перемещение · двойной щелчок — сброс. Нажмите категорию в легенде, чтобы скрыть или показать её."
        )
        a, b, c, d = st.columns(4)
        a.metric("Уникальных лауреатов", f"{filtered.laureate_id.nunique():,}")
        b.metric(
            "Награждений",
            f"{len(filtered):,}",
            help="Одна запись — один лауреат × одна премия.",
        )
        c.metric(
            "Стран происхождения",
            filtered[filtered.origin_country != UNKNOWN].origin_country.nunique(),
        )
        org_only = filtered.kind.eq("organization").all()
        median = (
            filtered.organization_age.median()
            if org_only
            else filtered[filtered.kind == "person"].award_age.median()
        )
        d.metric(
            "Лет от основания, медиана" if org_only else "Медианный возраст, лет",
            "—" if pd.isna(median) else f"{median:.0f}",
        )
        st.caption(
            f"Выборка: {years[0]}–{years[1]} · {filtered.prize_key.nunique()} премий «год × категория». Повторные премии не увеличивают число лауреатов."
        )
        st.markdown(
            '<div class="section-kicker">02 / ПОКОЛЕНИЯ И ДИСЦИПЛИНЫ</div>',
            unsafe_allow_html=True,
        )
        x, y = st.columns(2)
        with x:
            st.subheader("Ритм награждений")
            step = st.radio(
                "Группировка времени",
                ["По десятилетиям", "По годам"],
                horizontal=True,
                key="trend_step",
            )
            chart(
                charts.trend(filtered, 10 if step == "По десятилетиям" else 1), "trend"
            )
        with y:
            st.subheader("Шесть направлений")
            st.caption("Число награждений в выбранном срезе")
            chart(charts.categories(filtered), "categories")
        x, y = st.columns(2)
        with x:
            st.subheader(
                "Срок от основания до премии"
                if filtered.kind.eq("organization").all()
                else "Возраст признания"
            )
            bins = st.slider("Число интервалов", 8, 45, 20, key="age_bins")
            split = st.checkbox("Разделить возраст по категориям", key="age_split")
            chart(charts.ages(filtered, bins, split), "ages")
            exact = int((filtered.age_basis == "exact").sum())
            estimated = int((filtered.age_basis == "year_estimate").sum())
            if org_only:
                st.caption(
                    "Разность года премии и года основания. Это возраст организации в годах, а не возраст человека; записи без года основания исключены."
                )
            else:
                st.caption(
                    f"Точный возраст: {exact} награждений; оценка по годам: {estimated}. Организации исключены. Возраст рассчитан на dateAwarded; неполные даты дают оценку по годам."
                )
        with y:
            st.subheader("Страны основания" if org_only else "Страны рождения")
            top = st.slider("Стран в рейтинге", 5, 25, 12, key="country_top")
            historical = st.checkbox("Исторические названия стран", key="historical")
            chart(charts.countries(filtered, top, historical), "countries")
            st.caption(
                "Уникальные организации по месту основания."
                if org_only
                else "Уникальные люди по месту рождения. Это не гражданство и не рейтинг стран по качеству науки."
            )
        if org_only:
            st.subheader("Повторные награждения организаций")
            chart(charts.repeat_awards(filtered), "organization_repeats")
            st.caption("Число награждений каждой организации внутри текущей выборки.")
        else:
            st.subheader("Гендерный состав награждений")
            percent = st.checkbox(
                "Показывать доли в процентах", True, key="gender_percent"
            )
            chart(charts.gender(filtered, percent), "gender")
            st.caption(
                "Только люди. Каждое награждение учитывается отдельно; пол — по данным официального API."
            )
        migration_panel = st.expander(
            "Карта интеллектуальной миграции · рождение → работа",
            expanded=False,
            key="migration_panel",
            on_change="rerun",
        )
        if migration_panel.open:
            with migration_panel:
                st.markdown("### Связи между местами")
                st.write(
                    "Для людей: рождение → работа при награждении. Для организаций: основание → расположение из записи о премии. Это географическая связь, а не восстановленный маршрут переездов."
                )
                st.caption(
                    "Одна связь на лауреата: последняя выбранная премия с двумя координатами и первая подходящая аффилиация в порядке API. Порядок не означает «основное место работы»."
                )
                routes = service.routes(filtered, spec, one_per_person=True)
                unpaired = filtered[
                    (filtered.kind == "organization")
                    & ~filtered.laureate_id.isin(routes.laureate_id)
                ]
                f1, f2, f3 = st.columns(3)
                maximum = int(filtered.laureate_id.nunique())
                if "flow_limit" in st.session_state:
                    st.session_state["flow_limit"] = min(
                        maximum, max(0, int(st.session_state["flow_limit"]))
                    )
                if "flow_limit" not in st.session_state:
                    st.session_state["flow_limit"] = min(60, maximum)
                limit = f1.slider(
                    "Максимум связей на карте", 0, maximum, step=1, key="flow_limit"
                )
                opacity = f2.slider(
                    "Насыщенность линий", 0.05, 0.7, 0.24, key="flow_opacity"
                )
                choices = {"Все показанные": None}
                for row in (
                    filtered.drop_duplicates("laureate_id")
                    .sort_values("name")
                    .itertuples()
                ):
                    choices[f"{row.name} · {row.laureate_id}"] = row.laureate_id
                if st.session_state.get("flow_focus") not in choices:
                    st.session_state["flow_focus"] = "Все показанные"
                focus_label = f3.selectbox(
                    "Выделить лауреата", list(choices), key="flow_focus"
                )
                fig, shown, total = charts.flow_map(
                    routes,
                    limit,
                    opacity,
                    focus=choices[focus_label],
                    unpaired=unpaired,
                )
                chart(fig, "flow")
                st.markdown(
                    '<div class="legend">● Рождение · ◆ Основание организации → ★ Работа / расположение<br>◇ Только место основания: второго подтверждённого места нет. Цвет — категория премии.</div>',
                    unsafe_allow_html=True,
                )
                st.caption(
                    f"Пар координат: {total} из {maximum} лауреатов. Показано связей: {len(shown)}. Лимит 0 скрывает связи; одиночные основания остаются. При ограничении используется воспроизводимая случайная выборка. Для совпадающих мест дуга не рисуется."
                )
                if len(routes):
                    a, b, c = st.columns(3)
                    a.metric(
                        "Совпадающие места, до 1 км",
                        int((routes.distance_km <= 1).sum()),
                    )
                    known = routes[
                        (routes.origin_country != UNKNOWN) & (routes.work_country != "")
                    ]
                    b.metric(
                        "Разные страны",
                        int((known.origin_country != known.work_country).sum()),
                    )
                    c.metric(
                        "Медиана расстояния", f"{routes.distance_km.median():,.0f} км"
                    )
                    st.caption(
                        "Расстояние по дуге большого круга. Оно не измеряет длину пути миграции. Статистика использует все пары независимо от лимита карты."
                    )
                    top_routes = st.slider(
                        "Крупнейших потоков между странами", 1, 40, 18, key="sankey_top"
                    )
                    fig, covered = charts.sankey(routes, top_routes)
                    chart(fig, "sankey")
                    st.caption(
                        f"Слева — рождение / основание, справа — работа / расположение. В показанных потоках {covered} лауреатов; связи внутри страны сохранены."
                    )
                    st.download_button(
                        "Скачать все связи CSV",
                        csv_bytes(
                            routes.drop(
                                columns=["raw_json", "search_text"], errors="ignore"
                            )
                        ),
                        "nobel_routes.csv",
                        "text/csv",
                    )
                else:
                    st.info(
                        "В выборке нет двух подтверждённых мест для связи. На карте остаются известные места основания организаций."
                    )
        extra_charts_panel = st.expander(
            "Ещё три ракурса · эпохи, университеты, суммы",
            key="extra_charts_panel",
            on_change="rerun",
        )
        if extra_charts_panel.open:
            with extra_charts_panel:
                st.subheader("Категории по десятилетиям")
                chart(charts.heatmap(filtered), "heatmap")
                st.subheader("Центры знаний")
                n = st.slider(
                    "Организаций в рейтинге", 5, 25, 15, key="institution_top"
                )
                chart(
                    charts.institutions(filtered, service.filter_affiliations(spec), n),
                    "institutions",
                )
                st.caption(
                    "Один человек учитывается один раз в каждой организации. Итоги по организациям нельзя складывать: аффилиаций может быть несколько. Названия учреждений — как в API, без объединения исторических вариантов."
                )
                st.subheader("Денежный размер премии")
                adjusted = st.checkbox(
                    "prizeAmountAdjusted из API", True, key="adjusted_money"
                )
                chart(charts.money(filtered, adjusted), "money")
                st.caption(
                    "SEK, шведские кроны. Сумма на премию «год × категория», а не на человека; повторные получатели не увеличивают её. prizeAmountAdjusted показан как опубликован API; базовый год индексации здесь не предполагается."
                )
if catalog.open:
    with catalog:
        st.subheader("Лауреаты и их истории")
        st.write("Выберите лауреата. Поиск и фильтры слева сужают каталог.")
        people = (
            filtered[["laureate_id", "name", "name_ru", "kind_label"]]
            .drop_duplicates("laureate_id")
            .sort_values("name")
        )
        labels = {
            r.laureate_id: (f"{r.name_ru} / {r.name}" if r.name_ru else r.name)
            for r in people.itertuples()
        }
        selected = st.selectbox(
            "Лауреат",
            people.laureate_id.tolist(),
            format_func=lambda x: labels[x],
            key="person_id",
        )
        raw = load_person(str(DB), stamp, selected)
        render_card(
            raw,
            df[df.laureate_id == selected],
            filtered[filtered.laureate_id == selected],
            affiliations,
            cache,
        )
if lab.open:
    with lab:
        st.subheader("Соберите собственный вопрос")
        st.write(
            "Сводная таблица и график используют текущие фильтры. Выберите измерения и единицу подсчёта."
        )
        dimensions = {
            "Категория": "category_label",
            "Десятилетие": "decade",
            "Год": "award_year",
            "Страна рождения": "birth_country",
            "Город рождения": "birth_city",
            "Пол / тип": "gender_label",
        }
        a, b, c = st.columns(3)
        row = a.selectbox("Строки", list(dimensions), key="pivot_row")
        col = b.selectbox("Столбцы", list(dimensions), index=1, key="pivot_col")
        unit = c.selectbox(
            "Показатель",
            [
                "Награждения",
                "Уникальные лауреаты",
                "Медианный возраст",
                "Сумма долей премий",
            ],
            key="pivot_unit",
        )
        row_key, col_key = dimensions[row], dimensions[col]
        agg, value = {
            "Награждения": ("count", "award_key"),
            "Уникальные лауреаты": ("nunique", "laureate_id"),
            "Медианный возраст": ("median", "award_age"),
            "Сумма долей премий": ("sum", "share"),
        }[unit]
        if row_key == col_key:
            pivot = filtered.groupby(row_key)[value].agg(agg).to_frame(unit)
        else:
            pivot = filtered.pivot_table(
                index=row_key,
                columns=col_key,
                values=value,
                aggfunc=agg,
                fill_value=None if unit == "Медианный возраст" else 0,
            )
        st.dataframe(pivot, width="stretch")
        st.download_button(
            "Скачать сводную таблицу",
            csv_bytes(pivot.reset_index()),
            "nobel_pivot.csv",
            "text/csv",
        )
        st.caption(
            "Уникальные лауреаты в разных группах могут повторяться. Сумма долей использует portion из API; сумма по частично выбранным премиям может быть дробной."
        )
        if (
            len(pivot)
            and len(pivot.columns)
            and len(pivot) <= 80
            and len(pivot.columns) <= 40
        ):
            matrix = px.imshow(
                pivot.astype(float),
                aspect="auto",
                color_continuous_scale=["#F2F5EC", "#9EC6B9", "#256F77"],
                labels={"color": unit},
            )
            chart(charts.style(matrix, 420), "pivot_chart")
        else:
            st.caption(
                "Матрица слишком большая для читаемого графика. Сузьте фильтры или выберите более крупные группы."
            )
        st.subheader("Исходная аналитическая таблица")
        export = filtered.drop(columns=["raw_json", "search_text"], errors="ignore")
        default = [
            "name",
            "award_year",
            "category_label",
            "award_age",
            "birth_city",
            "birth_country",
            "institutions",
            "motivation",
        ]
        columns = st.multiselect(
            "Столбцы для просмотра и выгрузки",
            export.columns.tolist(),
            default=default,
            key="table_columns",
        )
        st.dataframe(export[columns], hide_index=True, width="stretch")
        st.download_button(
            "Скачать выбранные столбцы CSV",
            csv_bytes(export[columns]),
            "nobel_selection.csv",
            "text/csv",
        )
        selected_ids = tuple(sorted(set(filtered.laureate_id)))
        # Привязываем готовый файл к выборке и версии БД: старые фильтры не попадут в новый экспорт.
        export_key = (str(DB), stamp, selected_ids)
        if st.session_state.get("export_key") != export_key:
            st.session_state.pop("export_payload", None)
        if st.button("Подготовить полные записи JSON", key="prepare_full_json"):
            with st.spinner("Готовлю выбранные записи…"):
                payload = read_laureates(DB, selected_ids)
                st.session_state["export_payload"] = json.dumps(
                    payload, ensure_ascii=False, indent=2
                ).encode("utf-8")
                st.session_state["export_key"] = export_key
        if "export_payload" in st.session_state:
            st.download_button(
                "Скачать полные записи выбранных лауреатов JSON",
                st.session_state["export_payload"],
                "nobel_selected_full.json",
                "application/json",
                on_click="ignore",
            )
            st.caption(f"Готово: {len(selected_ids)} полных записей.")
        st.caption(
            "JSON сохраняет все поля официальной записи и все награждения выбранных людей; таблица CSV содержит только отфильтрованные награждения. Формульные префиксы в CSV экранированы."
        )
if about.open:
    with about:
        st.subheader("О данных и исследовании")
        st.write(
            "Nobel Atlas — учебный исследовательский проект Дениса Бреля. Он помогает изучать лауреатов, поколения и географию знаний на основе официального Nobel Prize API 2.1."
        )
        st.caption(
            "Фильтры слева действуют и здесь. Показатели полноты относятся к текущей выборке; объём всего снимка указан отдельно."
        )
        a, b, c = st.columns(3)
        a.metric("Лауреатов в полной базе", meta["laureate_count"])
        b.metric("Премий «год × категория»", meta["prize_count"])
        c.metric("Записей без лауреатов", int((prizes.awarded == 0).sum()))
        st.subheader("Полнота и точность — разные свойства")
        chart(charts.coverage(filtered, affiliations), "coverage")
        quality = charts.coverage_table(filtered, affiliations)
        st.dataframe(quality, hide_index=True, width="stretch")
        st.download_button(
            "Скачать оценку качества CSV",
            csv_bytes(quality),
            "nobel_data_quality.csv",
            "text/csv",
        )
        people = filtered[filtered.kind == "person"].drop_duplicates("laureate_id")
        partial = people[people.birth_date.notna() & ~people.birth_date_exact]
        if len(partial):
            st.info(
                f"В текущей выборке у {len(partial)} людей дата рождения неполная. Наличие записи не означает, что известны день и месяц. При неполной дате возраст оценивается разностью лет."
            )
            with st.expander("Посмотреть неполные даты"):
                st.dataframe(
                    partial[
                        ["name", "birth_date", "birth_city", "birth_country"]
                    ].rename(
                        columns={
                            "name": "Лауреат",
                            "birth_date": "Дата в API",
                            "birth_city": "Город",
                            "birth_country": "Страна",
                        }
                    ),
                    hide_index=True,
                    width="stretch",
                )
        else:
            st.success("В этой выборке нет людей с неполной записанной датой рождения.")
        st.markdown("### Как читать результаты")
        st.markdown("""
- **Лауреат** — уникальный человек или организация; повторное награждение не создаёт нового лауреата.
- **Награждение** — связь лауреата и премии. У одной премии может быть несколько получателей.
- **Премия** — год и категория. Денежная сумма учитывается один раз на премию, а не на каждого получателя.
- **Возраст** людей рассчитывается на дату присуждения из API, которая не обязательно совпадает с церемонией. Организации не включаются в возраст людей.
- **Происхождение** означает рождение человека или основание организации. Это не гражданство.
- **Работа** — официальная аффилиация при награждении; она не доказывает место открытия или учёбы.
- **Связи на карте** не восстанавливают реальный маршрут переездов. Неполнота данных различается между категориями.
""")
        st.markdown("### Организации и координаты")
        st.write(
            "У организаций используются место основания и расположение из записи о награждении. Если второго места нет, показан только контурный ромб основания. Города церемонии, современные штаб-квартиры и центры стран вместо неизвестных мест не подставляются."
        )
        st.write(
            "Если в записи нет координат, они могут быть дополнены из другой записи Nobel при точном совпадении города и страны и единственной паре координат. Источник дополнения подписан при наведении и в выгрузке. Первичные записи API остаются неизменными."
        )
        organizations = filtered[filtered.kind == "organization"].drop_duplicates(
            "laureate_id"
        )
        if len(organizations):
            with st.expander("Проверить географию организаций"):
                cols = [
                    "name",
                    "founded_date",
                    "origin_city",
                    "origin_country",
                    "origin_lat",
                    "origin_lon",
                    "origin_coord_source",
                ]
                st.dataframe(organizations[cols], hide_index=True, width="stretch")
        st.markdown("### Что хранится в базе")
        st.write(
            "Сохранены полные ответы обоих endpoint: laureates и nobelPrizes. Это имена на всех языках источника, формулировки заслуг, примечания, даты, доли и суммы, все аффилиации, места проживания, ссылки и записи о неприсуждённых премиях. Карточки и аналитические таблицы — представления этих записей; полный JSON можно скачать."
        )
        if cache:
            st.caption(
                f"Дополнительные сведения Wikidata представлены в {len(cache)} объектах кэша и отмечаются отдельно от Nobel API."
            )
        else:
            st.caption(
                "Этот снимок содержит сведения Nobel API. Биографии, образование и другие дополнительные сведения доступны по ссылкам на источники в карточках."
            )
        st.markdown("### Обновление и воспроизводимость")
        st.write(
            "Сайт читает готовый снимок SQLite. Автоматическое обновление выполняется отдельно, по понедельникам. Перед заменой проверяются полнота загрузки, согласованность двух endpoint и целостность базы; при ошибке сохраняется предыдущая версия."
        )
        st.caption(
            "Дата снимка показана внизу. Наличие расписания не гарантирует успешность каждого запуска; журнал обновления открыт в репозитории проекта."
        )
        registry = st.expander(
            "Реестр всех премий, включая неприсуждённые",
            key="prize_registry_panel",
            on_change="rerun",
        )
        if registry.open:
            with registry:
                prize_view = prizes[prizes.award_year.between(*years)]
                if cats:
                    prize_view = prize_view[prize_view.category.isin(cats)]
                st.caption(
                    "Реестр учитывает только годы и категории: фильтры людей неприменимы к премиям без лауреатов."
                )
                st.dataframe(
                    prize_view[
                        [
                            "award_year",
                            "category_label",
                            "awarded",
                            "date_awarded",
                            "prize_amount",
                            "prize_amount_adjusted",
                            "top_motivation",
                        ]
                    ],
                    hide_index=True,
                    width="stretch",
                )
                st.download_button(
                    "Все поля выбранных премий JSON",
                    json.dumps(
                        [json.loads(x) for x in prize_view.raw_json], ensure_ascii=False
                    ),
                    "nobel_prizes_full.json",
                    "application/json",
                )
        st.markdown(
            "[Документация Nobel API](https://www.nobelprize.org/about/developer-zone-2/) · [Условия использования](https://www.nobelprize.org/about/terms-of-use-for-api-nobelprize-org-and-data-nobelprize-org/)"
        )

render_footer(meta)
