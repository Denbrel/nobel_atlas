"""Streamlit entrypoint. Start with: streamlit run app.py"""
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
from nobel.ui import CSS, chart, render_card

st.set_page_config(page_title='Nobel Atlas · люди, открытия, места',page_icon='✦',layout='wide')
st.markdown(CSS,unsafe_allow_html=True)
DB=Path(os.getenv('NOBEL_DB',Path(__file__).with_name('nobel_database.sqlite')))

@st.cache_data(show_spinner=False)
def load_data(path,stamp):
    repo=DatabaseRepository(path)
    credits,affiliations,prizes=repo.read_frames()
    cache=repo.wikidata_cache()
    return prepare(credits,affiliations,cache),affiliations,prizes,repo.metadata(),cache

@st.cache_data(show_spinner=False)
def load_person(path,stamp,identifier):
    return DatabaseRepository(path).raw_laureate(identifier)

if not DB.exists():
    st.error('База данных не найдена. Загрузите nobel_database.sqlite из пакета проекта или выполните python updater.py.'); st.stop()
try:
    stamp=(DB.stat().st_mtime_ns,DB.stat().st_size)
    df,affiliations,prizes,meta,cache=load_data(str(DB),stamp)
except (sqlite3.Error,KeyError,ValueError) as exc:
    st.error('Нужна база формата Nobel Atlas 2. Запустите python updater.py для безопасного обновления.'); st.stop()
if df.empty:
    st.info('В базе пока нет награждений. Запустите обновление данных.'); st.stop()
service=AnalyticsService(df,affiliations)

def options(data,column):
    return sorted(x for x in data[column].dropna().unique() if x!='')

def reset_filters():
    for key in list(st.session_state):
        if key.startswith('flt_'): del st.session_state[key]

with st.sidebar:
    st.markdown('### ✦ NOBEL ATLAS')
    st.caption('Настройте свой исследовательский срез')
    st.button('Сбросить фильтры',on_click=reset_filters,width='stretch')
    query=st.text_input('Поиск по имени, мотивации и организации',placeholder='Например: Curie или quantum',key='flt_query')
    low,high=int(df.award_year.min()),int(df.award_year.max())
    years=st.slider('Год премии',low,high,(low,high),key='flt_years') if low<high else (low,high)
    cats=st.multiselect('Категории',options(df,'category'),format_func=lambda x:CATEGORIES.get(x,('',x))[1],key='flt_cats',placeholder='Все категории')
    kinds=st.multiselect('Тип лауреата',['person','organization'],format_func=lambda x:{'person':'Люди','organization':'Организации'}[x],key='flt_kinds',placeholder='Люди и организации')
    genders=st.multiselect('Пол / тип',options(df,'gender_label'),key='flt_gender',placeholder='Все')
    with st.expander('География рождения',expanded=True):
        birth_countries=st.multiselect('Страна рождения · современные названия',options(df,'birth_country'),key='flt_birth_country')
        birth_cities=st.multiselect('Город рождения',options(df[df.birth_country.isin(birth_countries)] if birth_countries else df,'birth_city'),key='flt_birth_city')
        continents=st.multiselect('Континент',options(df,'birth_continent'),key='flt_continent')
    with st.expander('Работа при награждении'):
        work_countries=st.multiselect('Страна работы',options(affiliations,'country_now'),key='flt_work_country')
        af=affiliations[affiliations.country_now.isin(work_countries)] if work_countries else affiliations
        work_cities=st.multiselect('Город работы',options(af,'city_now'),key='flt_work_city')
        if work_cities: af=af[af.city_now.isin(work_cities)]
        institutions=st.multiselect('Университет / организация',options(af,'name'),key='flt_institution')
    with st.expander('Возраст и дополнительные условия'):
        age=st.slider('Возраст при присуждении',0,110,(0,110),key='flt_age')
        include_unknown=st.checkbox('Включать неизвестный возраст и организации',True,key='flt_unknown_age')
        repeated=st.checkbox('Только многократные лауреаты',key='flt_repeated')
        geo_only=st.checkbox('Есть координаты рождения',key='flt_geo')
        death_countries=st.multiselect('Страна смерти',options(df,'death_country'),key='flt_death_country')
        statuses=st.multiselect('Статус премии в API',options(df,'prize_status'),key='flt_status')
    st.caption('Пустой список означает «все». Фильтры действуют на все вкладки. Названия мест сохранены на языке API.')
spec=FilterSpec(year_min=years[0],year_max=years[1],query=query,categories=cats,kinds=kinds,genders=genders,
    birth_countries=birth_countries,birth_cities=birth_cities,continents=continents,
    work_countries=work_countries,work_cities=work_cities,institutions=institutions,
    death_countries=death_countries,statuses=statuses,age_min=age[0],age_max=age[1],
    include_unknown_age=include_unknown,repeated_only=repeated,with_coordinates=geo_only)
filtered=service.filter(spec)
left,right=st.columns([3,1])
with left:
    st.markdown(f'<div class="eyebrow">ИССЛЕДОВАТЕЛЬСКИЙ АТЛАС · {low}—{high}</div><div class="hero-title">Нобелевская премия<br>в людях и местах</div><div class="hero-sub">Исследуйте открытия, поколения и географию знаний.<br>От общей картины — к истории каждого лауреата.</div>',unsafe_allow_html=True)
with right:
    updated=meta.get('updated_at','')[:10]
    st.markdown(f'<div class="hero-stamp">ОФИЦИАЛЬНЫЕ ОТКРЫТЫЕ ДАННЫЕ<br><b>Nobel Prize API 2.1</b><br>Снимок: {updated}<br>{meta["laureate_count"]:,} лауреатов · {meta["award_count"]:,} награждений</div>',unsafe_allow_html=True)
st.write('')
if filtered.empty:
    st.info('Для этой комбинации фильтров ничего не найдено. Измените параметры или нажмите «Сбросить фильтры».'); st.stop()
a,b,c,d=st.columns(4)
a.metric('Уникальных лауреатов',f'{filtered.laureate_id.nunique():,}')
b.metric('Награждений',f'{len(filtered):,}',help='Одна запись — один лауреат × одна премия. Премий по году и категории: '+str(filtered.prize_key.nunique()))
c.metric('Стран рождения',filtered[filtered.birth_country!=UNKNOWN].birth_country.nunique())
median=filtered[filtered.kind=='person'].award_age.median()
d.metric('Медианный возраст, лет','—' if pd.isna(median) else f'{median:.0f}')
st.caption(f'Выборка: {years[0]}–{years[1]} · {filtered.prize_key.nunique()} уникальных премий «год × категория». Повторные награждения не считаются новыми людьми.')
main,catalog,lab,about=st.tabs(['Обзор','Лауреаты','Лаборатория','О данных'])
with main:
    st.markdown('<div class="section-kicker">01 / ГЕОГРАФИЯ</div>',unsafe_allow_html=True)
    st.subheader('Где начинаются истории')
    m1,m2,m3=st.columns([2,1,1])
    mode=m1.selectbox('Что показать на карте',['Места рождения','Места работы','Места смерти'],key='map_mode')
    projection_label=m2.selectbox('Проекция',['Мир','Глобус'],key='map_projection')
    projection='natural earth' if projection_label=='Мир' else 'orthographic'
    dot_size=m3.slider('Размер точек',4,14,7,key='map_size')
    if mode=='Места работы':
        map_af=service.filter_affiliations(spec).merge(filtered[['award_key','name','award_year']],on='award_key',suffixes=('_institution',''))
        map_af=map_af.rename(columns={'name_institution':'institution','lat':'work_lat','lon':'work_lon','city_now':'work_city'})
        map_af=map_af.dropna(subset=['work_lat','work_lon'])
        chart(charts.work_map(map_af,projection,dot_size),'map_work')
        st.caption(f'★ Место работы при награждении · {len(map_af)} аффилиаций с координатами. Один лауреат может иметь несколько аффилиаций.')
    else:
        fig,n=charts.birth_map(filtered,'birth' if mode=='Места рождения' else 'death',projection,dot_size)
        chart(fig,'map_people')
        st.caption(f'● Один маркер — один уникальный лауреат · нанесено {n} из {filtered.laureate_id.nunique()}. Совпадающие точки могут перекрываться; измените масштаб или фильтры. Отсутствие координат не исключает человека из остальных графиков.')
    st.markdown('<div class="section-kicker">02 / ПОКОЛЕНИЯ И ДИСЦИПЛИНЫ</div>',unsafe_allow_html=True)
    x,y=st.columns(2)
    with x:
        st.subheader('Ритм награждений')
        step=st.radio('Группировка времени',['По десятилетиям','По годам'],horizontal=True,key='trend_step')
        chart(charts.trend(filtered,10 if step=='По десятилетиям' else 1),'trend')
    with y:
        st.subheader('Шесть направлений')
        st.caption('Число награждений в выбранном срезе')
        chart(charts.categories(filtered),'categories')
    x,y=st.columns(2)
    with x:
        st.subheader('Возраст признания')
        bins=st.slider('Число интервалов',8,45,20,key='age_bins')
        split=st.checkbox('Разделить возраст по категориям',key='age_split')
        chart(charts.ages(filtered,bins,split),'ages')
        exact=int((filtered.age_basis=='exact').sum()); estimated=int((filtered.age_basis=='year_estimate').sum())
        st.caption(f'Точный возраст: {exact} награждений; оценка по годам: {estimated}. Организации исключены. Возраст рассчитан на dateAwarded, при неполной дате — разность лет.')
    with y:
        st.subheader('Страны рождения')
        top=st.slider('Стран в рейтинге',5,25,12,key='country_top')
        historical=st.checkbox('Исторические названия стран',key='historical')
        chart(charts.countries(filtered,top,historical),'countries')
        st.caption('Уникальные люди по месту рождения. Это не гражданство и не рейтинг стран по качеству науки.')
    st.subheader('Гендерный состав награждений')
    percent=st.checkbox('Показывать доли в процентах',True,key='gender_percent')
    chart(charts.gender(filtered,percent),'gender')
    st.caption('Только люди. Каждое награждение учитывается отдельно; пол — по данным официального API.')
    with st.expander('Карта интеллектуальной миграции · рождение → работа',expanded=False):
        st.markdown('### Два места одной истории')
        st.write('Карта связывает место рождения с официальной аффилиацией при награждении. Она показывает географическую связь, а не реальный маршрут переездов или доказанное место открытия.')
        st.caption('Одна связь на человека: последнее выбранное награждение с координатами работы, затем первая доступная аффилиация в порядке API. Этот порядок не означает «основное место работы».')
        routes=service.routes(filtered,spec,one_per_person=True)
        f1,f2,f3=st.columns(3)
        limit=f1.slider('Максимум связей на карте',10,200,60,key='flow_limit')
        opacity=f2.slider('Насыщенность линий',.1,.7,.24,key='flow_opacity')
        choices={'Все показанные':None}
        choices.update({f'{r["name"]} · {r["laureate_id"]}':r['laureate_id'] for _,r in routes.sort_values('name').iterrows()})
        focus_label=f3.selectbox('Выделить одного лауреата',list(choices),key='flow_focus')
        fig,shown,total=charts.flow_map(routes,limit,opacity,focus=choices[focus_label])
        chart(fig,'flow')
        st.markdown('<div class="legend">● <b>Синий круг:</b> рождение &nbsp; → &nbsp; ★ <b>Золотая звезда:</b> работа при награждении<br>Тонкая дуга обозначает связь между местами. Направление читается от круга к звезде.</div>',unsafe_allow_html=True)
        st.caption(f'Связи с координатами: {len(routes)} из {filtered[filtered.kind=="person"].laureate_id.nunique()} людей. На карте {len(shown)} из {total} связей длиннее 1 км. При ограничении используется воспроизводимая случайная выборка; статистика ниже считается по всем подходящим связям.')
        if len(routes):
            a,b,c=st.columns(3)
            a.metric('Связей короче 1 км',int((routes.distance_km<=1).sum()))
            known=routes[(routes.birth_country!=UNKNOWN)&(routes.work_country!='')]
            b.metric('Разные страны',int((known.birth_country!=known.work_country).sum()))
            c.metric('Медиана расстояния',f'{routes.distance_km.median():,.0f} км')
            st.caption('Расстояние по дуге большого круга; не длина пути миграции. Страны сравниваются по современным названиям.')
            top_routes=st.slider('Крупнейших потоков между странами',5,40,18,key='sankey_top')
            fig,covered=charts.sankey(routes,top_routes); chart(fig,'sankey')
            st.caption(f'Слева — рождение, справа — работа. Показано {covered} человек в крупнейших {top_routes} потоках; остальные потоки не отображены. Связи внутри одной страны сохранены.')
            st.download_button('Скачать все связи CSV',csv_bytes(routes.drop(columns=['raw_json','search_text'],errors='ignore')),'nobel_routes.csv','text/csv')
        else: st.info('Нет пар координат для этих фильтров. Для мира и литературы аффилиации часто отсутствуют.')
    with st.expander('Ещё три ракурса · эпохи, университеты, суммы'):
        st.subheader('Категории по десятилетиям'); chart(charts.heatmap(filtered),'heatmap')
        st.subheader('Центры знаний')
        n=st.slider('Организаций в рейтинге',5,25,15,key='institution_top')
        chart(charts.institutions(filtered,service.filter_affiliations(spec),n),'institutions')
        st.caption('Один человек учитывается один раз в каждой организации. Итоги по организациям нельзя складывать: аффилиаций может быть несколько. Названия учреждений — как в API, без объединения исторических вариантов.')
        st.subheader('Денежный размер премии')
        adjusted=st.checkbox('prizeAmountAdjusted из API',True,key='adjusted_money')
        chart(charts.money(filtered,adjusted),'money')
        st.caption('SEK, шведские кроны. Сумма на премию «год × категория», а не на человека; повторные получатели не увеличивают её. prizeAmountAdjusted показан как опубликован API; базовый год индексации здесь не предполагается.')
with catalog:
    st.subheader('Люди за открытиями')
    st.write('Выберите лауреата. Поиск и фильтры слева сужают каталог.')
    people=filtered[['laureate_id','name','name_ru','kind_label']].drop_duplicates('laureate_id').sort_values('name')
    labels={r.laureate_id:(f'{r.name_ru} / {r.name}' if r.name_ru else r.name) for r in people.itertuples()}
    selected=st.selectbox('Лауреат',people.laureate_id.tolist(),format_func=lambda x:labels[x],key='person_id')
    raw=load_person(str(DB),stamp,selected)
    render_card(raw,df[df.laureate_id==selected],filtered[filtered.laureate_id==selected],affiliations,cache)
with lab:
    st.subheader('Соберите собственный вопрос')
    st.write('Сводная таблица и график используют текущие фильтры. Выберите измерения и единицу подсчёта.')
    dimensions={'Категория':'category_label','Десятилетие':'decade','Год':'award_year','Страна рождения':'birth_country','Город рождения':'birth_city','Пол / тип':'gender_label'}
    a,b,c=st.columns(3)
    row=a.selectbox('Строки',list(dimensions),key='pivot_row')
    col=b.selectbox('Столбцы',list(dimensions),index=1,key='pivot_col')
    unit=c.selectbox('Показатель',['Награждения','Уникальные лауреаты','Медианный возраст','Сумма долей премий'],key='pivot_unit')
    row_key,col_key=dimensions[row],dimensions[col]
    agg,value={'Награждения':('count','award_key'),'Уникальные лауреаты':('nunique','laureate_id'),
               'Медианный возраст':('median','award_age'),'Сумма долей премий':('sum','share')}[unit]
    if row_key==col_key:
        pivot=filtered.groupby(row_key)[value].agg(agg).to_frame(unit)
    else:
        pivot=filtered.pivot_table(index=row_key,columns=col_key,values=value,aggfunc=agg,fill_value=None if unit=='Медианный возраст' else 0)
    st.dataframe(pivot,width='stretch')
    st.download_button('Скачать сводную таблицу',csv_bytes(pivot.reset_index()),'nobel_pivot.csv','text/csv')
    st.caption('Уникальные лауреаты в разных группах могут повторяться. Сумма долей использует portion из API; сумма по частично выбранным премиям может быть дробной.')
    if len(pivot) and len(pivot.columns) and len(pivot)<=80 and len(pivot.columns)<=40:
        matrix=px.imshow(pivot.astype(float),aspect='auto',color_continuous_scale=['#F2F5EC','#9EC6B9','#256F77'],labels={'color':unit})
        chart(charts.style(matrix,420),'pivot_chart')
    else: st.caption('Матрица слишком большая для читаемого графика. Сузьте фильтры или выберите более крупные группы.')
    st.subheader('Исходная аналитическая таблица')
    export=filtered.drop(columns=['raw_json','search_text'],errors='ignore')
    default=['name','award_year','category_label','award_age','birth_city','birth_country','institutions','motivation']
    columns=st.multiselect('Столбцы для просмотра и выгрузки',export.columns.tolist(),default=default,key='table_columns')
    st.dataframe(export[columns],hide_index=True,width='stretch')
    st.download_button('Скачать выбранные столбцы CSV',csv_bytes(export[columns]),'nobel_selection.csv','text/csv')
    selected_ids=set(filtered.laureate_id)
    st.download_button('Скачать полные записи выбранных лауреатов JSON',
        json.dumps([load_person(str(DB),stamp,x) for x in sorted(selected_ids)],ensure_ascii=False),
        'nobel_selected_full.json','application/json')
    st.caption('JSON сохраняет все поля официальной записи и все награждения выбранных людей; таблица CSV содержит только отфильтрованные награждения. Формульные префиксы в CSV экранированы.')
with about:
    st.subheader('Данные, которым можно задать вопросы')
    st.write('Оба официальных endpoint сохранены целиком, включая все языки, ссылки, примечания, сведения об организациях, места проживания, все аффилиации и записи о неприсуждённых премиях. Для аналитики вложенные данные разложены по связанным таблицам SQLite.')
    a,b,c=st.columns(3)
    a.metric('Лауреатов в полной базе',meta['laureate_count'])
    b.metric('Записей год × категория',meta['prize_count'])
    c.metric('Без лауреатов в API',int((prizes.awarded==0).sum()))
    st.subheader('Полнота текущей выборки')
    chart(charts.coverage(filtered,affiliations),'coverage')
    st.caption('Рождение и его координаты — доля уникальных людей; точный возраст — доля награждений людей; координаты работы — доля всех выбранных награждений. Отсутствие сведений о смерти не считается ошибкой.')
    st.markdown('''**Как читать результаты**

- Рождение, гражданство, проживание и аффилиация — разные признаки. Они не подменяют друг друга.
- Аффилиация при награждении не доказывает, где сделано открытие или где человек учился.
- Координаты обычно относятся к городу, а не к зданию университета. Центры стран не используются вместо городов.
- Официальные даты могут быть неполными (`YYYY-00-00`). Возраст в таком случае приблизительный.
- Отсутствие координат влияет только на карты. Люди и организации остаются в основной статистике.
- «Экономика» включает премию памяти Альфреда Нобеля; официальное полное название хранится в JSON.
- Карта отражает неполноту исторических сведений и различия между дисциплинами, а не причинный эффект миграции.
''')
    if cache:
        st.info(f'Wikidata: {len(cache)} объектов в локальном кэше. Дополнения подписаны отдельно; исторические квалификаторы сохранены в JSON.')
    else:
        st.info('В этом снимке используются официальные данные Nobel API. Дополнительный импорт Wikidata уже реализован: python updater.py --wikidata. Перед запуском укажите NOBEL_USER_AGENT с адресом своего проекта.')
    with st.expander('Реестр всех премий, включая неприсуждённые'):
        prize_view=prizes[prizes.award_year.between(*years)]
        if cats: prize_view=prize_view[prize_view.category.isin(cats)]
        st.caption('Этот реестр учитывает только годы и категории: фильтры людей неприменимы к премиям без лауреатов.')
        columns=['award_year','category_label','awarded','date_awarded','prize_amount','prize_amount_adjusted','top_motivation']
        st.dataframe(prize_view[columns],hide_index=True,width='stretch')
        st.download_button('Все поля выбранных премий JSON',json.dumps([json.loads(x) for x in prize_view.raw_json],ensure_ascii=False), 'nobel_prizes_full.json','application/json')
    st.markdown('[Официальный API и документация](https://www.nobelprize.org/about/developer-zone-2/) · [Условия использования данных API](https://www.nobelprize.org/about/terms-of-use-for-api-nobelprize-org-and-data-nobelprize-org/) · [Правила запросов Wikidata](https://www.mediawiki.org/wiki/API:Etiquette)')
    st.caption('Веб-приложение читает готовую базу. Обновление выполняется отдельно в GitHub Actions; запросы посетителей не запускают парсинг.')
st.markdown('<div class="footer">NOBEL ATLAS · Учебный исследовательский проект<br>Данные: Nobel Prize API / Nobel Prize Outreach. Географическая подложка: Natural Earth / Plotly. Проект не связан с Нобелевским фондом.</div>',unsafe_allow_html=True)
