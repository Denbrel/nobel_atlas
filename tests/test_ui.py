"""Автоматические проверки: пользовательские сценарии через Streamlit AppTest."""

from pathlib import Path
from streamlit.testing.v1 import AppTest
import json
from nobel.storage import DatabaseRepository

APP = Path(__file__).resolve().parents[1] / "app.py"


def start(monkeypatch):
    monkeypatch.delenv("NOBEL_DB", raising=False)
    return AppTest.from_file(str(APP), default_timeout=45).run()


def test_ui_filters_empty_state_and_map_modes(monkeypatch):
    at = start(monkeypatch)
    assert not at.exception and len(at.tabs) == 4
    assert len(at.get("plotly_chart")) == 6
    # Hidden pages must not produce tables, JSON or whole-dataset downloads.
    assert not at.dataframe and not at.json
    assert not any(x.key == "prepare_full_json" for x in at.button)
    at.selectbox(key="map_mode").select("Работа / расположение").run()
    assert not at.exception
    at.selectbox(key="map_mode").select("Места смерти").run()
    assert not at.exception
    at.multiselect(key="flt_kinds").set_value(["organization"]).run()
    assert not at.exception
    at.text_input(key="flt_query").set_value("NO_SUCH_LAUREATE_987654321").run()
    assert not at.exception and len(at.info) > 0 and not at.metric
    at.button[0].click().run()
    assert not at.exception and len(at.metric) > 0


def test_search_and_lazy_tabs(monkeypatch):
    at = start(monkeypatch)
    at.text_input(key="flt_query").set_value("Curie").run()
    assert not at.exception
    assert int(at.metric[0].value.replace(",", "")) >= 3
    at.checkbox(key="age_split").check().run()
    at.radio(key="trend_step").set_value("По годам").run()
    at.session_state["main_tabs"] = "Лауреаты"
    at.run()
    assert not at.exception and at.selectbox(key="person_id")
    assert not at.json
    at.session_state["raw_record_panel"] = True
    at.run()
    assert not at.exception and at.json
    at.session_state["main_tabs"] = "Лаборатория"
    at.run()
    at.selectbox(key="pivot_unit").select("Медианный возраст").run()
    at.selectbox(key="pivot_row").select("Страна рождения").run()
    assert not at.exception and len(at.get("plotly_chart")) == 1
    at.button(key="prepare_full_json").click().run()
    assert not at.exception


def test_all_charts_still_available_on_demand(monkeypatch):
    at = start(monkeypatch)
    at.session_state["migration_panel"] = True
    at.run()
    assert not at.exception and len(at.get("plotly_chart")) == 8
    at.session_state["extra_charts_panel"] = True
    at.run()
    assert not at.exception and len(at.get("plotly_chart")) == 11
    at.session_state["main_tabs"] = "О данных"
    at.run()
    assert not at.exception and len(at.get("plotly_chart")) == 1
    at.session_state["prize_registry_panel"] = True
    at.run()
    assert not at.exception and at.dataframe


def test_flow_limit_and_organization_navigation(monkeypatch):
    """От нуля до числа лауреатов, без сбоя при резком сужении фильтра."""
    at = start(monkeypatch)
    assert json.loads(at.get("plotly_chart")[0].proto.config)["scrollZoom"] is True
    at.session_state["migration_panel"] = True
    at.run()
    slider = at.slider(key="flow_limit")
    assert slider.min == 0 and slider.max == int(at.metric[0].value.replace(",", ""))
    slider.set_value(slider.max).run()
    assert not at.exception
    at.multiselect(key="flt_kinds").set_value(["organization"]).run()
    assert not at.exception
    assert at.slider(key="flow_limit").max == int(at.metric[0].value.replace(",", ""))
    at.slider(key="flow_limit").set_value(0).run()
    assert not at.exception
    at.session_state["main_tabs"] = "Лауреаты"
    at.run()
    assert not at.exception
    assert any("основания" in item.label for item in at.metric)
    at.session_state["main_tabs"] = "О данных"
    at.run()
    assert not at.exception
    assert not any("NOBEL_USER_AGENT" in item.value for item in at.caption)


def test_export_works_without_old_repository_method_and_invalidates_selection(
    monkeypatch,
):
    """Повторяет AttributeError пользователя: старый класс не должен ломать экспорт."""
    monkeypatch.delattr(DatabaseRepository, "raw_laureates")
    at = start(monkeypatch)
    at.session_state["main_tabs"] = "Лаборатория"
    at.run()
    at.button(key="prepare_full_json").click().run()
    assert not at.exception
    first = json.loads(at.session_state["export_payload"])
    assert len(first) > 500
    at.text_input(key="flt_query").set_value("Curie").run()
    assert "export_payload" not in at.session_state
    at.button(key="prepare_full_json").click().run()
    assert not at.exception
    second = json.loads(at.session_state["export_payload"])
    assert 0 < len(second) < len(first)
    at.run()
    assert at.session_state[
        "export_payload"
    ]  # Файл остаётся доступен после перерисовки.
