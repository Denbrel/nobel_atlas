"""Consistent Plotly views, with explicit counting units."""
from html import escape
import numpy as np
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from .models import CATEGORIES
from .analysis import great_circle

COLORS = {v[1]: v[2] for v in CATEGORIES.values()}
INK, TEAL, GOLD = '#213E49', '#287D80', '#B68A3A'

def style(fig, height=340, geo=False):
    fig.update_layout(template='plotly_white', height=height, paper_bgcolor='rgba(0,0,0,0)',
        plot_bgcolor='rgba(0,0,0,0)', font=dict(family='Arial, sans-serif', color=INK, size=12),
        margin=dict(l=12,r=12,t=15,b=25), legend=dict(title=None, orientation='h', y=-0.18, x=0),
        hoverlabel=dict(bgcolor='#FFFFFF', font_size=12))
    if not geo:
        fig.update_xaxes(gridcolor='#E9EDEA', zeroline=False)
        fig.update_yaxes(gridcolor='#E9EDEA', zeroline=False)
    return fig

def map_style(fig, projection='natural earth', height=450):
    style(fig, height, geo=True)
    fig.update_geos(projection_type=projection, resolution=110, showframe=False,
        showcountries=True, countrycolor='#D0DAD7', countrywidth=.5,
        showcoastlines=True, coastlinecolor='#C1CECC', coastlinewidth=.5,
        showland=True, landcolor='#EEF1EA', showocean=True, oceancolor='#F8FAF7',
        bgcolor='rgba(0,0,0,0)', lataxis_range=[-60, 85])
    return fig

def birth_map(df, mode='birth', projection='natural earth', size=7):
    base = df.drop_duplicates('laureate_id').copy()
    lat, lon = ('birth_lat', 'birth_lon') if mode == 'birth' else ('death_lat', 'death_lon')
    place = 'birth_city' if mode == 'birth' else 'death_city'
    country = 'birth_country' if mode == 'birth' else 'death_country'
    base = base.dropna(subset=[lat, lon])
    categories = df.groupby('laureate_id').category_label.agg(lambda v: ', '.join(sorted(set(v))))
    years = df.groupby('laureate_id').award_year.agg(lambda v: ', '.join(map(str, sorted(set(v)))))
    base['categories'] = base.laureate_id.map(categories); base['years'] = base.laureate_id.map(years)
    fig = go.Figure(go.Scattergeo(lat=base[lat], lon=base[lon], mode='markers',
        marker=dict(size=size, color=TEAL, opacity=.6, line=dict(width=.5,color='#FFFFFF')),
        text=[f'<b>{escape(r["name"])}</b><br>{escape(r[place])}, {escape(r[country])}<br>{escape(r["categories"])} · {r["years"]}' for _,r in base.iterrows()],
        hovertemplate='%{text}<extra></extra>', name='Лауреаты', showlegend=False))
    return map_style(fig, projection), len(base)

def work_map(routes, projection='natural earth', size=7):
    fig = go.Figure(go.Scattergeo(lat=routes.work_lat, lon=routes.work_lon, mode='markers',
        marker=dict(symbol='star', size=size+2, color=GOLD, opacity=.65),
        text=[f'<b>{escape(r["name"])}</b><br>{escape(r["institution"])}<br>{escape(r["work_city"])} · {int(r["award_year"])}' for _,r in routes.iterrows()],
        hovertemplate='%{text}<extra></extra>', showlegend=False))
    return map_style(fig, projection)

def trend(df, step=10):
    d = df.assign(period=(df.award_year // step)*step)
    grouped = d.groupby(['period','category_label']).size().rename('count').reset_index()
    if len(grouped):
        index = pd.MultiIndex.from_product([range(int(grouped.period.min()),int(grouped.period.max())+step,step), sorted(df.category_label.unique())], names=['period','category_label'])
        grouped = grouped.set_index(['period','category_label']).reindex(index,fill_value=0).reset_index()
    fig = px.area(grouped, x='period', y='count', color='category_label', color_discrete_map=COLORS,
        labels={'period':'Год' if step==1 else 'Начало десятилетия','count':'Награждения','category_label':'Категория'})
    return style(fig)

def categories(df):
    d=df.groupby('category_label').size().sort_values().rename('count').reset_index()
    fig=px.bar(d,y='category_label',x='count',color='category_label',color_discrete_map=COLORS,
        orientation='h',text='count',labels={'category_label':'','count':'Награждения'})
    fig.update_layout(showlegend=False); fig.update_traces(textposition='outside',cliponaxis=False)
    return style(fig)

def ages(df, bins=20, split=False):
    d=df[df.kind=='person'].dropna(subset=['award_age'])
    fig=px.histogram(d,x='award_age',color='category_label' if split else None, nbins=bins,
        color_discrete_map=COLORS, color_discrete_sequence=[TEAL],
        labels={'award_age':'Возраст на дату присуждения','category_label':'Категория'},barmode='stack')
    fig.update_layout(yaxis_title='Награждения'); return style(fig)

def countries(df, top=12, historical=False):
    col='birth_country_historical' if historical else 'birth_country'
    d=df[df.kind=='person'].drop_duplicates('laureate_id')
    d=d[d[col]!='Не указано'].groupby(col).size().nlargest(top).sort_values().rename('count').reset_index()
    fig=px.bar(d,x='count',y=col,orientation='h',text='count',color_discrete_sequence=[TEAL],
        labels={'count':'Уникальные лауреаты',col:''})
    return style(fig)

def gender(df, percent=True):
    d=df[df.kind=='person'].groupby(['decade','gender_label']).size().rename('count').reset_index()
    d['percent']=100*d['count']/d.groupby('decade')['count'].transform('sum')
    fig=px.bar(d,x='decade',y='percent' if percent else 'count',color='gender_label',
        color_discrete_map={'Мужчины':'#73999F','Женщины':'#B68A3A','Не указано':'#B4B9B5'},
        labels={'decade':'Десятилетие','percent':'Доля награждений, %','count':'Награждения','gender_label':'Пол'})
    return style(fig)

def heatmap(df):
    data=pd.crosstab(df.category_label,df.decade)
    fig=px.imshow(data,aspect='auto',text_auto=True,color_continuous_scale=['#F3F5EF','#93BBB2','#236E73'],
        labels={'x':'Десятилетие','y':'Категория','color':'Награждения'})
    fig.update_layout(coloraxis_showscale=False); return style(fig)

def institutions(df, affiliations, top=15):
    a=affiliations[affiliations.award_key.isin(df.award_key)].merge(df[['award_key','laureate_id']],on='award_key')
    # One laureate counts once in each institution; these counts are not additive.
    d=a.groupby('name').laureate_id.nunique().nlargest(top).sort_values().rename('count').reset_index()
    fig=px.bar(d,x='count',y='name',orientation='h',color_discrete_sequence=[TEAL],
        labels={'count':'Уникальные лауреаты в организации','name':''})
    return style(fig,max(350,top*26))

def money(df, adjusted=True):
    d=df.drop_duplicates('prize_key').sort_values('award_year').copy()
    col='prize_amount_adjusted' if adjusted else 'prize_amount'; d['million']=d[col]/1e6
    fig=px.line(d,x='award_year',y='million',color='category_label',color_discrete_map=COLORS,
        labels={'award_year':'Год','million':'Сумма премии, млн SEK','category_label':'Категория'})
    return style(fig)

def flow_map(routes, limit=60, opacity=.24, projection='natural earth', focus=None):
    eligible = routes[routes.distance_km > 1].copy()
    if focus:
        shown=eligible[eligible.laureate_id==focus]
    else:
        # Stable seeded sample, explicitly disclosed in the UI. No misleading top ranking.
        shown=eligible.sample(n=min(limit,len(eligible)),random_state=42).sort_values('name')
    fig=go.Figure(); lats=[]; lons=[]
    for r in shown.itertuples():
        lat,lon=great_circle(r.birth_lat,r.birth_lon,r.work_lat,r.work_lon)
        lats+=lat+[None]; lons+=lon+[None]
    fig.add_trace(go.Scattergeo(lat=lats,lon=lons,mode='lines',line=dict(color=f'rgba(66,116,125,{opacity})',width=1.1 if not focus else 2.2),
        hoverinfo='skip',name='Рождение → работа',showlegend=True))
    for prefix,symbol,color,label,size in [('birth','circle','#578C9B','Рождение',5),('work','star','#BD974D','Работа при награждении',9)]:
        hover=[f'<b>{escape(r["name"])}</b><br>{escape(r["birth_city"])} → {escape(r["work_city"])}<br>{escape(r["institution"])}<br>{int(r["award_year"])} · {r["distance_km"]:,.0f} км по прямой' for _,r in shown.iterrows()]
        fig.add_trace(go.Scattergeo(lat=shown[prefix+'_lat'],lon=shown[prefix+'_lon'],mode='markers',
            marker=dict(symbol=symbol,color=color,size=size,opacity=.85,line=dict(width=.4,color='#FFFFFF')),
            text=hover,hovertemplate='%{text}<extra></extra>',name=label))
    return map_style(fig,projection,510),shown,len(eligible)

def sankey(routes, top=18):
    d=routes[(routes.birth_country!='Не указано') & (routes.work_country!='')]
    counts=d.groupby(['birth_country','work_country']).size().nlargest(top).reset_index(name='count')
    origins=sorted(counts.birth_country.unique()); destinations=sorted(counts.work_country.unique())
    labels=origins+destinations
    fig=go.Figure(go.Sankey(arrangement='snap',node=dict(pad=18,thickness=13,
        label=labels,color=['#6F9EA4']*len(origins)+['#C3A05F']*len(destinations)),
        link=dict(source=[origins.index(x) for x in counts.birth_country],
                  target=[len(origins)+destinations.index(x) for x in counts.work_country],
                  value=counts['count'],color='rgba(103,147,150,.22)',
                  hovertemplate='%{source.label} → %{target.label}: %{value}<extra></extra>')))
    return style(fig,430),int(counts['count'].sum())

def coverage(df, affiliations):
    people=df[df.kind=='person'].drop_duplicates('laureate_id')
    with_work=set(affiliations.dropna(subset=['lat','lon']).award_key)
    values={'Дата рождения':people.birth_date.notna().mean(),
        'Координаты рождения':(people.birth_lat.notna() & people.birth_lon.notna()).mean(),
        'Точный возраст':df[df.kind=='person'].age_basis.eq('exact').mean(),
        'Координаты работы':df.award_key.isin(with_work).mean()}
    fig=go.Figure(go.Bar(x=[100*v if pd.notna(v) else 0 for v in values.values()],y=list(values),
        orientation='h',marker_color=TEAL,texttemplate='%{x:.1f}%',textposition='auto'))
    fig.update_xaxes(range=[0,100],title='Заполненность, %'); return style(fig,260)
