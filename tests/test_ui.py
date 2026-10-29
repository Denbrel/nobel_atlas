from pathlib import Path
from streamlit.testing.v1 import AppTest

APP=Path(__file__).resolve().parents[1]/'app.py'


def start(monkeypatch):
    monkeypatch.delenv('NOBEL_DB',raising=False)
    return AppTest.from_file(str(APP),default_timeout=45).run()


def test_ui_filters_empty_state_and_map_modes(monkeypatch):
    at=start(monkeypatch)
    assert not at.exception and len(at.tabs)==4
    assert len(at.get('plotly_chart'))==6
    # Hidden pages must not produce tables, JSON or whole-dataset downloads.
    assert not at.dataframe and not at.json
    assert not any(x.key=='prepare_full_json' for x in at.button)
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


def test_search_and_lazy_tabs(monkeypatch):
    at=start(monkeypatch)
    at.text_input(key='flt_query').set_value('Curie').run()
    assert not at.exception
    assert int(at.metric[0].value.replace(',',''))>=3
    at.checkbox(key='age_split').check().run()
    at.radio(key='trend_step').set_value('По годам').run()
    at.session_state['main_tabs']='Лауреаты';at.run()
    assert not at.exception and at.selectbox(key='person_id')
    assert not at.json
    at.session_state['raw_record_panel']=True;at.run()
    assert not at.exception and at.json
    at.session_state['main_tabs']='Лаборатория';at.run()
    at.selectbox(key='pivot_unit').select('Медианный возраст').run()
    at.selectbox(key='pivot_row').select('Страна рождения').run()
    assert not at.exception and len(at.get('plotly_chart'))==1
    at.button(key='prepare_full_json').click().run()
    assert not at.exception


def test_all_charts_still_available_on_demand(monkeypatch):
    at=start(monkeypatch)
    at.session_state['migration_panel']=True;at.run()
    assert not at.exception and len(at.get('plotly_chart'))==8
    at.session_state['extra_charts_panel']=True;at.run()
    assert not at.exception and len(at.get('plotly_chart'))==11
    at.session_state['main_tabs']='О данных';at.run()
    assert not at.exception and len(at.get('plotly_chart'))==1
    at.session_state['prize_registry_panel']=True;at.run()
    assert not at.exception and at.dataframe
