"""Pure filtering and aggregation. A row is one laureate–prize credit."""
from dataclasses import dataclass, field
import math
import unicodedata
import pandas as pd

UNKNOWN = 'Не указано'
GENDERS = {'male': 'Мужчины', 'female': 'Женщины'}

def fold(value):
    return ''.join(c for c in unicodedata.normalize('NFKD', str(value)).casefold() if not unicodedata.combining(c))

def prepare(credits, affiliations, cache=None):
    df = credits.copy()
    df['gender_label'] = df['gender'].map(GENDERS).fillna(UNKNOWN)
    df.loc[df.kind == 'organization', 'gender_label'] = 'Организации'
    df['kind_label'] = df.kind.map({'person': 'Люди', 'organization': 'Организации'})
    for col in ('birth_city', 'birth_country', 'birth_country_historical', 'birth_continent', 'death_country', 'death_city'):
        df[col] = df[col].replace('', UNKNOWN).fillna(UNKNOWN)
    df['decade'] = (df.award_year // 10) * 10
    df['name_ru'] = df.wikidata_id.map(lambda q: (cache or {}).get(q, {}).get('data', {}).get('labels', {}).get('ru', {}).get('value', ''))
    df['description'] = df.wikidata_id.map(lambda q: description((cache or {}).get(q, {}).get('data', {})))
    names = affiliations.groupby('award_key')['name'].agg(' | '.join) if len(affiliations) else pd.Series(dtype=str)
    df['institutions'] = df.award_key.map(names).fillna('')
    df['search_text'] = (df[['name', 'full_name', 'name_ru', 'motivation', 'description', 'institutions']]
                         .fillna('').astype(str).agg(' '.join, axis=1).map(fold))
    return df

def description(entity):
    descriptions = entity.get('descriptions', {})
    return (descriptions.get('ru') or descriptions.get('en') or {}).get('value', '')

@dataclass
class FilterSpec:
    year_min: int = 1901
    year_max: int = 9999
    query: str = ''
    categories: list[str] = field(default_factory=list)
    kinds: list[str] = field(default_factory=list)
    genders: list[str] = field(default_factory=list)
    birth_countries: list[str] = field(default_factory=list)
    birth_cities: list[str] = field(default_factory=list)
    continents: list[str] = field(default_factory=list)
    death_countries: list[str] = field(default_factory=list)
    work_countries: list[str] = field(default_factory=list)
    work_cities: list[str] = field(default_factory=list)
    institutions: list[str] = field(default_factory=list)
    statuses: list[str] = field(default_factory=list)
    age_min: int = 0
    age_max: int = 110
    include_unknown_age: bool = True
    repeated_only: bool = False
    with_coordinates: bool = False

class AnalyticsService:
    def __init__(self, credits, affiliations):
        self.credits = credits
        self.affiliations = affiliations
    def filter(self, spec):
        df = self.credits
        mask = df.award_year.between(spec.year_min, spec.year_max)
        for col, values in [
            ('category', spec.categories), ('kind', spec.kinds), ('gender_label', spec.genders),
            ('birth_country', spec.birth_countries), ('birth_city', spec.birth_cities),
            ('birth_continent', spec.continents), ('death_country', spec.death_countries),
            ('prize_status', spec.statuses)]:
            if values:
                mask &= df[col].isin(values)
        for token in fold(spec.query).split():
            mask &= df.search_text.str.contains(token, regex=False, na=False)
        mask &= df.award_age.between(spec.age_min, spec.age_max) | (df.award_age.isna() & spec.include_unknown_age)
        if spec.repeated_only:
            repeated = df.groupby('laureate_id').prize_key.nunique()
            mask &= df.laureate_id.isin(repeated[repeated > 1].index)
        if spec.with_coordinates:
            mask &= df.birth_lat.notna() & df.birth_lon.notna()
        if spec.work_countries or spec.work_cities or spec.institutions:
            a = self.filter_affiliations(spec)
            mask &= df.award_key.isin(a.award_key)
        return df[mask].copy()
    def filter_affiliations(self, spec):
        a = self.affiliations
        # All geography/institution conditions must match the SAME affiliation.
        for col, values in [('country_now', spec.work_countries), ('city_now', spec.work_cities), ('name', spec.institutions)]:
            if values:
                a = a[a[col].isin(values)]
        return a
    def routes(self, selected, spec, one_per_person=True):
        a = self.filter_affiliations(spec).rename(columns={'lat': 'work_lat', 'lon': 'work_lon',
            'name': 'institution', 'city_now': 'work_city', 'country_now': 'work_country', 'coord_source': 'work_coord_source'})
        merged = selected.merge(a[['award_key', 'ordinal', 'institution', 'work_lat', 'work_lon', 'work_city', 'work_country', 'work_coord_source']], on='award_key')
        merged = merged[merged.kind == 'person'].dropna(subset=['birth_lat', 'birth_lon', 'work_lat', 'work_lon'])
        merged = merged.sort_values(['award_year', 'ordinal', 'prize_key'], ascending=[False, True, True])
        if one_per_person:
            merged = merged.drop_duplicates('laureate_id')
        merged['distance_km'] = merged.apply(lambda r: haversine(r.birth_lat, r.birth_lon, r.work_lat, r.work_lon), axis=1) if len(merged) else pd.Series(dtype=float)
        return merged

def haversine(lat1, lon1, lat2, lon2):
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dlat, dlon = p2 - p1, math.radians(lon2 - lon1)
    a = math.sin(dlat/2)**2 + math.cos(p1)*math.cos(p2)*math.sin(dlon/2)**2
    return 6371.0088 * 2 * math.asin(math.sqrt(min(1, max(0, a))))

def great_circle(lat1, lon1, lat2, lon2, steps=32):
    def vec(lat, lon):
        lat, lon = math.radians(lat), math.radians(lon)
        return (math.cos(lat)*math.cos(lon), math.cos(lat)*math.sin(lon), math.sin(lat))
    u, v = vec(lat1, lon1), vec(lat2, lon2)
    omega = math.acos(min(1, max(-1, sum(a*b for a,b in zip(u,v)))))
    # Near coincident/antipodal endpoints have no uniquely stable interpolation.
    if abs(math.sin(omega)) < 1e-9:
        return [lat1, lat2], [lon1, lon2]
    lats, lons = [], []
    for t in range(steps + 1):
        w = t/steps
        xyz = [(math.sin((1-w)*omega)*a + math.sin(w*omega)*b)/math.sin(omega) for a,b in zip(u,v)]
        lat = math.degrees(math.atan2(xyz[2], math.hypot(xyz[0], xyz[1])))
        lon = math.degrees(math.atan2(xyz[1], xyz[0]))
        if lons and lons[-1] is not None and abs(lon - lons[-1]) > 180:
            lats.append(None); lons.append(None)
        lats.append(lat); lons.append(lon)
    return lats, lons

def csv_bytes(df):
    """Prevent spreadsheet formula execution in exports containing source text."""
    safe = df.copy()
    for col in safe.select_dtypes(include=['object', 'string']).columns:
        safe[col] = safe[col].map(lambda v: "'" + v if isinstance(v, str) and v.lstrip().startswith(('=', '+', '-', '@')) else v)
    return safe.to_csv(index=False).encode('utf-8-sig')
