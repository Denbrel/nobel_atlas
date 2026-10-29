"""Presentation helpers; all source HTML is escaped or rendered as plain text."""
from html import escape
import json
from urllib.parse import urlparse
import pandas as pd
import streamlit as st
from .models import text, Place, CATEGORIES
from .analysis import description

CSS = '''<style>
.stApp{background:#F8F9F5;color:#213E49}
.block-container{padding-top:2.2rem;padding-bottom:3rem;max-width:1480px}
h1,h2,h3{letter-spacing:-.025em;color:#213E49} h1{font-family:Georgia,serif;font-weight:500!important}
[data-testid="stSidebar"]{background:#EEF2EC;border-right:1px solid #DDE5DD}
[data-testid="stSidebar"] .block-container{padding-top:1.3rem}
[data-testid="stMetric"]{background:#FFFFFF;border:1px solid #E1E8DF;border-radius:14px;padding:16px 20px}
[data-testid="stMetricLabel"]{color:#667C7B;font-size:.8rem}
[data-testid="stMetricValue"]{color:#246D72;font-family:Georgia,serif}
[data-testid="stTabs"] button{font-size:.95rem}
[data-testid="stExpander"]{border-radius:14px;border-color:#DAE3DB;background:#FFFFFF}
[data-testid="stPlotlyChart"]{border-radius:10px}
.eyebrow{font-size:.72rem;letter-spacing:.15em;font-weight:700;color:#6B8582;margin-bottom:9px}
.hero-title{font:500 clamp(2rem,4vw,3.5rem)/1.08 Georgia,serif;letter-spacing:-.04em;margin:0 0 16px;color:#213E49}
.hero-sub{max-width:740px;font-size:1rem;color:#647D7B;line-height:1.6}
.hero-stamp{border-left:2px solid #C3A15F;padding:12px 18px;color:#617C78;font-size:.85rem;line-height:1.8;margin-top:20px}
.section-kicker{font-size:.7rem;font-weight:700;letter-spacing:.12em;color:#8B9F97;margin-top:16px}
.profile{background:linear-gradient(125deg,#163E4B,#2F6970);padding:30px;border-radius:18px;color:#F5F7EF;margin:16px 0 20px}
.profile-name{font:500 clamp(1.8rem,3vw,2.6rem)/1.2 Georgia,serif;margin:12px 0;color:#FFF}
.profile-meta{color:#BFD2CC;font-size:.9rem;line-height:1.7}
.profile-initials{height:64px;width:64px;display:flex;align-items:center;justify-content:center;border-radius:50%;background:#E5D8B5;color:#234A53;font:26px Georgia,serif;float:right}
.badge{display:inline-block;border:1px solid #729391;border-radius:20px;padding:5px 12px;font-size:.78rem;margin:4px 5px 0 0;color:#F5ECD5}
.motivation{font:1.1rem/1.7 Georgia,serif;color:#2E545C;background:#F0F4EE;border-left:3px solid #B89A5B;padding:16px 20px;border-radius:0 10px 10px 0}
.legend{font-size:.84rem;color:#5B7775;line-height:1.8;padding:7px 0}
.footer{border-top:1px solid #DDE6DC;padding-top:18px;margin-top:32px;color:#788D87;font-size:.77rem;line-height:1.7}
@media(max-width:700px){.block-container{padding-left:1rem;padding-right:1rem}.profile{padding:20px}.hero-stamp{margin-top:0}}
</style>'''

def date_label(value):
    if not value:
        return 'Не указана'
    parts=str(value).split('-')
    if len(parts)==3:
        if parts[1]=='00': return parts[0]+' (известен только год)'
        if parts[2]=='00': return '-'.join(parts[:2])+' (без дня)'
    return str(value)

def link_button(label, url):
    if url and urlparse(url).scheme == 'https':
        st.link_button(label,url,width='stretch')

def chart(fig, key):
    st.plotly_chart(fig,width='stretch',key=key,theme=None,
        config={'displaylogo':False,'scrollZoom':False,'responsive':True,
                'toImageButtonOptions':{'format':'png','scale':2}, 'topojsonURL':'app/static/'})

def render_card(raw, all_credits, matching, affiliations, cache):
    name=text(raw.get('knownName') or raw.get('orgName'))
    entity=cache.get(raw.get('wikidata',{}).get('id'),{}).get('data',{})
    ru=entity.get('labels',{}).get('ru',{}).get('value','')
    initials=''.join(x[0] for x in name.split()[:2] if x)
    badges=''.join(f'<span class="badge">{int(r.award_year)} · {escape(r.category_label)}</span>' for r in all_credits.sort_values('award_year').itertuples())
    is_org='orgName' in raw
    birth=raw.get('founded' if is_org else 'birth',{})
    st.markdown(f'''<div class="profile"><div class="profile-initials">{escape(initials)}</div>
        <div class="eyebrow" style="color:#ACCCC6">{'ОРГАНИЗАЦИЯ' if is_org else 'ЛАУРЕАТ'} · NOBEL #{escape(str(raw['id']))}</div>
        <div class="profile-name">{escape(ru or name)}</div>
        <div class="profile-meta">{escape(name) if ru else escape(text(raw.get('fullName')))}<br>
        {'Основание' if is_org else 'Рождение'}: {escape(date_label(birth.get('date')))} · {escape(str(Place.from_api(birth.get('place'))))}</div>
        {badges}</div>''',unsafe_allow_html=True)
    bio=description(entity)
    if bio:
        st.write(bio); st.caption('Краткое описание: Wikidata. Полные биографии доступны по ссылкам на источники.')
    c1,c2,c3=st.columns(3)
    c1.metric('Награждений за всю жизнь',len(all_credits))
    dates=all_credits.sort_values('award_year')
    first_age=dates.iloc[0].award_age
    c2.metric('Возраст при первой премии','—' if pd.isna(first_age) else f'{int(first_age)} лет')
    c3.metric('Первая премия',str(int(dates.iloc[0].award_year)))
    if len(matching)!=len(all_credits):
        st.caption('Карточка показывает все награждения выбранного лауреата, включая не вошедшие в текущие фильтры.')
    for award in raw.get('nobelPrizes',[]):
        category=text(award.get('category')); year=award.get('awardYear')
        st.markdown(f'#### {year} · {CATEGORIES.get(category,("",category))[1]}')
        st.markdown(f'<div class="motivation">{escape(text(award.get("motivation")))}</div>',unsafe_allow_html=True)
        st.caption('Официальная формулировка Нобелевского комитета · язык оригинальных данных')
        a,b,c=st.columns(3)
        a.write(f'**Дата присуждения:** {date_label(award.get("dateAwarded"))}')
        b.write(f'**Доля премии:** {award.get("portion","—")}')
        c.write(f'**Статус API:** {award.get("prizeStatus","—")}')
        st.caption('dateAwarded — дата присуждения из API; это не обязательно дата церемонии или фактического вручения.')
        if award.get('topMotivation'): st.write(text(award['topMotivation']))
        places=[]
        for aff in award.get('affiliations',[]):
            p=Place.from_api(aff)
            places.append({'Организация':text(aff.get('name')),'Город':p.city_now,'Страна сейчас':p.country_now,
                'Историческая страна':p.country,'Координаты API':str(p.point) if p.point else 'Не указаны'})
        if places:
            st.dataframe(pd.DataFrame(places),hide_index=True,width='stretch')
        else:
            st.caption('Место работы при награждении не указано. Город церемонии вместо него не подставляется.')
        for residence in award.get('residences',[]):
            st.write('**Место проживания из API:** '+str(Place.from_api(residence)))
    details,extra=st.columns(2)
    with details:
        st.markdown('#### Биографические сведения')
        for label,key in [('Рождение','birth'),('Смерть','death'),('Основание','founded')]:
            if key in raw:
                event=raw[key]; p=Place.from_api(event.get('place'))
                st.write(f'**{label}:** {date_label(event.get("date"))} · {p}')
                if p.point: st.caption(f'Координаты города: {p.point}')
                if p.country and p.country!=p.country_now: st.caption('Название страны в тот период: '+p.country)
        if not is_org and 'death' not in raw: st.caption('В API нет сведений о смерти; это само по себе не доказывает, что человек жив.')
        for key,label in [('nativeName','Имя на родном языке'),('penName','Псевдоним'),('acronym','Аббревиатура')]:
            if raw.get(key): st.write(f'**{label}:** {text(raw[key])}')
    with extra:
        st.markdown('#### Источники и дополнительные сведения')
        official=next((x['href'] for x in raw.get('links',[]) if x.get('rel')=='external'),'')
        link_button('Нобелевский комитет ↗',official)
        link_button('Wikipedia ↗',raw.get('wikipedia',{}).get('english'))
        link_button('Wikidata ↗',raw.get('wikidata',{}).get('url'))
        for prop,label in [('P69','Образование'),('P108','Работодатели за всю жизнь'),('P27','Гражданство'),('P106','Профессии'),('P101','Области исследований')]:
            values=[]
            for claim in entity.get('claims',{}).get(prop,[]):
                if claim.get('rank')=='deprecated': continue
                value=claim.get('mainsnak',{}).get('datavalue',{}).get('value',{})
                if isinstance(value,dict) and value.get('id'):
                    qid=value['id']; labels=cache.get(qid,{}).get('data',{}).get('labels',{})
                    values.append((labels.get('ru') or labels.get('en') or {}).get('value',qid))
            if values: st.write(f'**{label} · Wikidata:** '+', '.join(dict.fromkeys(values)))
    raw_record_panel=st.expander('Полная запись API, примечания и все языковые версии', key='raw_record_panel', on_change='rerun')
    if raw_record_panel.open:
        with raw_record_panel:
            st.json(raw,expanded=False)
            st.download_button('Скачать запись JSON',json.dumps(raw,ensure_ascii=False,indent=2),
                file_name=f'nobel_{raw["id"]}.json',mime='application/json')
            if entity:
                st.caption('Wikidata: исходные утверждения, квалификаторы времени и ссылки на источники')
                st.json(entity,expanded=False)
