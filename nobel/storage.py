"""SQLite repository. Build a complete staging database, then atomically replace."""
from contextlib import closing
from datetime import datetime, timezone
from fractions import Fraction
import hashlib
import json
import os
from pathlib import Path
import shutil
import sqlite3
import tempfile
from .models import NobelDataset, Place, GeoPoint, text, year, age_at

SCHEMA_VERSION = 2

def dumps(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'))

def utcnow():
    return datetime.now(timezone.utc).isoformat(timespec='seconds')

def digest(value):
    return hashlib.sha256(dumps(value).encode()).hexdigest()

def insert(conn, table, row):
    # Table/column names only come from the application's own schema.
    conn.execute(f'INSERT INTO {table} ({",".join(row)}) VALUES ({",".join("?" for _ in row)})', list(row.values()))

PLACE_COLUMNS = ('city', 'country', 'city_now', 'country_now', 'continent', 'lat', 'lon', 'coord_source')

def city_qid(raw):
    values = raw.get('cityNow', {}).get('sameAs', [])
    if isinstance(values, str):
        values = [values]
    for value in values:
        if '/wiki/Q' in value and 'wikidata.org/' in value:
            return value.rsplit('/', 1)[-1]
    return None

def place_fields(place, prefix='', cache=None):
    point, source = place.point, 'Nobel API' if place.point else ''
    qid = city_qid(place.raw)
    if not point and cache and qid in cache:
        claims = cache[qid]['data'].get('claims', {}).get('P625', [])
        usable = [c for c in claims if c.get('rank') != 'deprecated']
        preferred = [c for c in usable if c.get('rank') == 'preferred']
        for claim in preferred or usable:
            value = claim.get('mainsnak', {}).get('datavalue', {}).get('value', {})
            if isinstance(value, dict) and str(value.get('globe', '')).endswith('/Q2'):
                point = GeoPoint.from_api(value)
                if point:
                    source = f'Wikidata:{qid}'; break
    values = [place.city, place.country, place.city_now, place.country_now, place.continent,
              point.lat if point else None, point.lon if point else None, source]
    return {prefix + k: v for k, v in zip(PLACE_COLUMNS, values)}

class DatabaseRepository:
    def __init__(self, path='nobel_database.sqlite'):
        self.path = Path(path).resolve()
    def connect(self):
        conn = sqlite3.connect(self.path.as_uri() + '?mode=ro', uri=True)
        conn.row_factory = sqlite3.Row
        return conn
    def metadata(self):
        if not self.path.exists():
            return {}
        try:
            with closing(self.connect()) as c:
                return {r['key']: json.loads(r['value']) for r in c.execute('SELECT * FROM metadata')}
        except sqlite3.OperationalError:
            return {'schema_version': 1}
    def wikidata_cache(self):
        if self.metadata().get('schema_version') != SCHEMA_VERSION:
            return {}
        with closing(self.connect()) as c:
            return {r['qid']: {'data': json.loads(r['raw_json']), 'fetched_at': r['fetched_at']}
                    for r in c.execute('SELECT * FROM wikidata_entities')}
    def raw_snapshot(self):
        with closing(self.connect()) as c:
            results = {}
            for endpoint in ('laureates', 'nobelPrizes'):
                pages = [json.loads(r[0]) for r in c.execute('SELECT raw_json FROM source_pages WHERE endpoint=? ORDER BY page_no', (endpoint,))]
                results[endpoint] = {'items': [item for page in pages for item in page[endpoint]], 'pages': pages}
            return results
    def raw_laureate(self, identifier):
        with closing(self.connect()) as c:
            row = c.execute('SELECT raw_json FROM laureates WHERE id=?', (str(identifier),)).fetchone()
            return json.loads(row[0]) if row else None
    def raw_laureates(self, identifiers):
        """Batch export with one connection; don't open a database per person."""
        ids = sorted(set(map(str, identifiers)))
        result = []
        with closing(self.connect()) as c:
            # Keep below SQLite builds with the historical 999-parameter limit.
            for start in range(0, len(ids), 500):
                batch = ids[start:start + 500]
                marks = ','.join('?' for _ in batch)
                rows = c.execute(f'SELECT raw_json FROM laureates WHERE id IN ({marks}) ORDER BY id', batch)
                result.extend(json.loads(row[0]) for row in rows)
        return result
    def read_frames(self):
        import pandas as pd
        with closing(self.connect()) as c:
            credits = pd.read_sql_query('''SELECT a.*, p.scheme, p.award_year, p.category,
                p.category_label, p.date_awarded, p.prize_amount, p.prize_amount_adjusted,
                p.top_motivation, l.name, l.full_name, l.kind, l.gender,
                l.birth_date, l.death_date, l.founded_date, l.birth_year,
                l.birth_city_now AS birth_city, l.birth_country_now AS birth_country,
                l.birth_country AS birth_country_historical, l.birth_continent,
                l.birth_lat, l.birth_lon, l.birth_coord_source,
                l.death_city_now AS death_city, l.death_country_now AS death_country,
                l.death_lat, l.death_lon, l.wikidata_id, l.nobel_url, l.wikipedia_url
                FROM awards a JOIN prizes p ON p.prize_key=a.prize_key
                JOIN laureates l ON l.id=a.laureate_id''', c)
            affiliations = pd.read_sql_query('SELECT * FROM affiliations', c)
            prizes = pd.read_sql_query('SELECT * FROM prizes', c)
        return credits, affiliations, prizes
    @staticmethod
    def _schema(conn):
        place = ','.join(f'{prefix}{col} {"REAL" if col in ("lat","lon") else "TEXT"}'
                         for prefix in ('birth_', 'death_', 'founded_') for col in PLACE_COLUMNS)
        conn.executescript(f'''
        PRAGMA foreign_keys=ON;
        CREATE TABLE metadata(key TEXT PRIMARY KEY, value TEXT NOT NULL);
        CREATE TABLE source_pages(endpoint TEXT, page_no INTEGER, raw_json TEXT NOT NULL, PRIMARY KEY(endpoint,page_no));
        CREATE TABLE laureates(id TEXT PRIMARY KEY, name TEXT NOT NULL, full_name TEXT, kind TEXT NOT NULL,
            gender TEXT, birth_date TEXT, death_date TEXT, founded_date TEXT,
            birth_year INTEGER, death_year INTEGER, wikidata_id TEXT, nobel_url TEXT,
            wikipedia_url TEXT, {place}, raw_json TEXT NOT NULL);
        CREATE TABLE prizes(prize_key TEXT PRIMARY KEY, scheme TEXT, award_year INTEGER,
            category TEXT, category_label TEXT, full_name TEXT, date_awarded TEXT,
            prize_amount INTEGER, prize_amount_adjusted INTEGER, top_motivation TEXT,
            awarded INTEGER, raw_json TEXT NOT NULL);
        CREATE TABLE awards(award_key TEXT PRIMARY KEY, laureate_id TEXT REFERENCES laureates(id),
            prize_key TEXT REFERENCES prizes(prize_key), portion TEXT, share REAL,
            sort_order INTEGER, prize_status TEXT, motivation TEXT, award_age INTEGER,
            age_basis TEXT, raw_json TEXT NOT NULL, UNIQUE(laureate_id,prize_key));
        CREATE TABLE affiliations(id INTEGER PRIMARY KEY, award_key TEXT REFERENCES awards(award_key),
            ordinal INTEGER, name TEXT, city TEXT, country TEXT, city_now TEXT, country_now TEXT,
            continent TEXT, lat REAL, lon REAL, coord_source TEXT, raw_json TEXT NOT NULL);
        CREATE TABLE residences(id INTEGER PRIMARY KEY, award_key TEXT REFERENCES awards(award_key),
            ordinal INTEGER, city TEXT, country TEXT, city_now TEXT, country_now TEXT,
            continent TEXT, lat REAL, lon REAL, coord_source TEXT, raw_json TEXT NOT NULL);
        CREATE TABLE wikidata_entities(qid TEXT PRIMARY KEY, fetched_at TEXT, raw_json TEXT NOT NULL);
        CREATE INDEX awards_laureate ON awards(laureate_id);
        CREATE INDEX awards_prize ON awards(prize_key);
        CREATE INDEX prizes_year_category ON prizes(award_year,category);
        CREATE INDEX affiliation_credit ON affiliations(award_key);
        ''')
    def install(self, snapshots, wikidata=None, allow_count_decrease=False):
        from .models import CATEGORIES
        dataset = NobelDataset(snapshots['laureates']['items'], snapshots['nobelPrizes']['items'])
        dataset.validate()
        # Validate pagination even for files loaded in offline mode.
        for endpoint, snapshot in snapshots.items():
            pages = snapshot['pages']; offset = 0
            for page in pages:
                if int(page['meta']['count']) != len(snapshot['items']) or int(page['meta']['offset']) != offset:
                    raise ValueError(f'Invalid source pagination: {endpoint}')
                offset += len(page[endpoint])
            if [x for p in pages for x in p[endpoint]] != snapshot['items']:
                raise ValueError('Raw pages and extracted items disagree')
        meta = self.metadata()
        if self.path.exists() and not allow_count_decrease:
            with closing(self.connect()) as old:
                previous = old.execute('SELECT COUNT(*) FROM laureates').fetchone()[0]
                old_prizes = old.execute('SELECT COUNT(*) FROM prizes').fetchone()[0]
            if len(dataset) < previous or (meta.get('schema_version') == 2 and len(dataset.prizes) < old_prizes):
                raise ValueError('Source record count decreased; review before --allow-count-decrease')
        cache = self.wikidata_cache() if wikidata is None else wikidata
        fingerprint = digest({'schema': SCHEMA_VERSION, 'sources': snapshots, 'wikidata': cache})
        if fingerprint == meta.get('content_hash'):
            return False
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd, stage = tempfile.mkstemp(prefix='.nobel-stage-', suffix='.sqlite', dir=self.path.parent); os.close(fd)
        try:
            with closing(sqlite3.connect(stage)) as c:
                self._schema(c)
                with c:
                    for endpoint, snapshot in snapshots.items():
                        for i, page in enumerate(snapshot['pages']):
                            insert(c, 'source_pages', {'endpoint': endpoint, 'page_no': i, 'raw_json': dumps(page)})
                    for p in dataset.prizes:
                        r = p.raw
                        insert(c, 'prizes', {'prize_key': p.key, 'scheme': p.scheme, 'award_year': p.year,
                            'category': p.category, 'category_label': CATEGORIES.get(p.category, ('', p.category))[1],
                            'full_name': text(r.get('categoryFullName')), 'date_awarded': r.get('dateAwarded'),
                            'prize_amount': r.get('prizeAmount'), 'prize_amount_adjusted': r.get('prizeAmountAdjusted'),
                            'top_motivation': text(r.get('topMotivation')), 'awarded': int(bool(r.get('laureates'))),
                            'raw_json': dumps(r)})
                    for l in dataset:
                        r = l.raw; birth = r.get('birth', {}).get('date'); death = r.get('death', {}).get('date')
                        row = {'id': l.id, 'name': l.name, 'full_name': text(r.get('fullName') or r.get('orgName')),
                            'kind': l.kind, 'gender': r.get('gender'), 'birth_date': birth, 'death_date': death,
                            'founded_date': r.get('founded', {}).get('date'), 'birth_year': year(birth),
                            'death_year': year(death), 'wikidata_id': r.get('wikidata', {}).get('id'),
                            'nobel_url': next((x['href'] for x in r.get('links', []) if x.get('rel') == 'external'), ''),
                            'wikipedia_url': r.get('wikipedia', {}).get('english'), 'raw_json': dumps(r)}
                        for prefix, place in [('birth_', l.birth), ('death_', l.death), ('founded_', l.founded)]:
                            row.update(place_fields(place, prefix, cache))
                        insert(c, 'laureates', row)
                        for credit in l.awards:
                            a = credit.raw; key = f'{credit.prize.key}:{l.id}'
                            age, basis = age_at(birth, a.get('dateAwarded'), credit.prize.year) if l.kind == 'person' else (None, 'organization')
                            share = float(Fraction(a['portion'])) if a.get('portion') else None
                            if share is not None and not 0 < share <= 1:
                                raise ValueError('Invalid prize portion')
                            insert(c, 'awards', {'award_key': key, 'laureate_id': l.id, 'prize_key': credit.prize.key,
                                'portion': a.get('portion'), 'share': share, 'sort_order': int(a.get('sortOrder', 0)),
                                'prize_status': a.get('prizeStatus'), 'motivation': text(a.get('motivation')),
                                'award_age': age, 'age_basis': basis, 'raw_json': dumps(a)})
                            for i, place in enumerate(credit.affiliations):
                                insert(c, 'affiliations', {'award_key': key, 'ordinal': i,
                                    'name': text(place.raw.get('name')), **place_fields(place, cache=cache), 'raw_json': dumps(place.raw)})
                            for i, raw in enumerate(a.get('residences', [])):
                                insert(c, 'residences', {'award_key': key, 'ordinal': i,
                                    **place_fields(Place.from_api(raw), cache=cache), 'raw_json': dumps(raw)})
                    for qid, cached in sorted(cache.items()):
                        insert(c, 'wikidata_entities', {'qid': qid, 'fetched_at': cached['fetched_at'], 'raw_json': dumps(cached['data'])})
                    metadata = {'schema_version': SCHEMA_VERSION, 'content_hash': fingerprint,
                        'updated_at': utcnow(), 'laureate_count': len(dataset), 'prize_count': len(dataset.prizes),
                        'award_count': sum(len(l.awards) for l in dataset),
                        'official_source': 'https://api.nobelprize.org/2.1/',
                        'wikidata_entities': len(cache)}
                    for key, value in metadata.items():
                        insert(c, 'metadata', {'key': key, 'value': dumps(value)})
                if c.execute('PRAGMA integrity_check').fetchone()[0] != 'ok' or c.execute('PRAGMA foreign_key_check').fetchall():
                    raise ValueError('Database validation failed')
            if self.path.exists():
                shutil.copy2(self.path, str(self.path) + '.bak')
            os.replace(stage, self.path)
            return True
        finally:
            if os.path.exists(stage):
                os.unlink(stage)
