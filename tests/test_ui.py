from pathlib import Path
from streamlit.testing.v1 import AppTest

APP=Path(__file__).resolve().parents[1]/'app.py'

def test_ui_filters_empty_state_and_map_modes(monkeypatch):
    monkeypatch.delenv('NOBEL_DB',raising=False)
    at=AppTest.from_file(str(APP),default_timeout=45).run()
    assert not at.exception and len(at.tabs)==4
    assert len(at.get('plotly_chart'))>=12
    at.selectbox(key='map_mode').select('Места работы').run()
    assert not at.exception
    at.selectbox(key='map_mode').select('Места смерти').run()
    assert not at.exception
    at.multiselect(key='flt_kinds').set_value(['organization']).run()
    assert not at.exception
    at.text_input(key='flt_query').set_value('NO_SUCH_LAUREATE_987654321').run()
    assert not at.exception and len(at.info)>0 and not at.metric
    at.button[0].click().run()
    assert not at.exception and len(at.metric)>0

def test_search_repeated_laureate_and_advanced_controls(monkeypatch):
    monkeypatch.delenv('NOBEL_DB',raising=False)
    at=AppTest.from_file(str(APP),default_timeout=45).run()
    at.text_input(key='flt_query').set_value('Curie').run()
    assert not at.exception
    assert int(at.metric[0].value.replace(',',''))>=3
    at.checkbox(key='age_split').check().run()
    at.radio(key='trend_step').set_value('По годам').run()
    at.selectbox(key='pivot_unit').select('Медианный возраст').run()
    at.selectbox(key='pivot_row').select('Страна рождения').run()
    assert not at.exception
