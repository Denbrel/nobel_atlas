import copy
import sqlite3
import pytest
from nobel.models import GeoPoint, Laureate, NobelDataset, age_at, text, Place
from nobel.storage import DatabaseRepository, place_fields
from nobel.sources import NobelClient, PoliteHTTP
from updater import IngestionPipeline, UpdateLock

@pytest.mark.parametrize('birth,awarded,y,expected',[
 ('1980-12-11','2000-10-01',2000,(19,'exact')),
 ('1980-10-01','2000-10-01',2000,(20,'exact')),
 ('1980-00-00','2000-10-01',2000,(20,'year_estimate')),
 (None,'2000-10-01',2000,(None,'unknown')),
 ('2001-01-01','2000-10-01',2000,(None,'unknown')),
 ('1900-02-29','1950-10-01',1950,(50,'year_estimate'))])
def test_age(birth,awarded,y,expected):
    assert age_at(birth,awarded,y)==expected

def test_domain_and_zero_coordinates(snapshots):
    assert GeoPoint.from_api({'latitude':'0','longitude':'0'})==GeoPoint(0,0)
    assert GeoPoint.from_api({'latitude':'NaN','longitude':'10'}) is None
    with pytest.raises(ValueError): GeoPoint(91,0)
    a=Laureate.from_api(snapshots['laureates']['items'][0])
    assert a==Laureate.from_api(a.raw) and len({a,a})==1
    d=NobelDataset(snapshots['laureates']['items'],snapshots['nobelPrizes']['items'])
    assert len(d)==3 and d[0]==next(iter(d)); assert str(a)=='Alice Example'
    assert str(a.birth.point)=='0.0000, 0.0000'

def test_full_raw_and_multiple_affiliations(repo,snapshots):
    assert repo.raw_laureate('1')==snapshots['laureates']['items'][0]
    assert repo.raw_snapshot()==snapshots
    df,a,p=repo.read_frames()
    assert len(df)==4 and len(a)==3 and len(p)==3
    assert len(df[df.laureate_id=='2'])==1
    assert df[df.laureate_id=='3'].award_age.isna().all()
    assert text({'en':'for <I>discovery</I> &amp; work'})=='for discovery & work'

def test_idempotent(repo,snapshots):
    before=repo.path.read_bytes(); stamp=repo.path.stat().st_mtime_ns
    assert repo.install(snapshots) is False
    assert repo.path.read_bytes()==before and repo.path.stat().st_mtime_ns==stamp

def test_mismatch_does_not_replace(repo,snapshots):
    before=repo.path.read_bytes(); damaged=copy.deepcopy(snapshots)
    damaged['laureates']['items'][0]['nobelPrizes'].pop()
    with pytest.raises(ValueError,match='disagree'): repo.install(damaged)
    assert repo.path.read_bytes()==before

def test_failure_during_insert_does_not_replace(repo,snapshots):
    before=repo.path.read_bytes(); damaged=copy.deepcopy(snapshots)
    damaged['laureates']['items'][0]['nobelPrizes'][0]['portion']='invalid'
    with pytest.raises(ValueError): repo.install(damaged)
    assert repo.path.read_bytes()==before
    assert not list(repo.path.parent.glob('.nobel-stage-*'))

def test_partial_snapshot_and_duplicate_rejected(repo,snapshots):
    damaged=copy.deepcopy(snapshots); damaged['laureates']['pages'][0]['meta']['count']=100
    with pytest.raises(ValueError,match='pagination'): repo.install(damaged)
    damaged=copy.deepcopy(snapshots); damaged['laureates']['items'].append(damaged['laureates']['items'][0])
    with pytest.raises(ValueError,match='Duplicate'): repo.install(damaged)

def test_shrink_guard(repo,snapshots):
    damaged=copy.deepcopy(snapshots)
    damaged['laureates']['items'].pop(); damaged['nobelPrizes']['items'].pop()
    for endpoint,data in damaged.items(): data['pages'][0]['meta']['count']=len(data['items'])
    with pytest.raises(ValueError,match='decreased'): repo.install(damaged)

def test_safe_legacy_upgrade(tmp_path,snapshots):
    path=tmp_path/'old.sqlite'
    with sqlite3.connect(path) as c:
        c.execute('CREATE TABLE laureates(id TEXT)'); c.execute('INSERT INTO laureates VALUES ("old")')
        c.execute('CREATE TABLE prizes(id TEXT)')
    before=path.read_bytes(); r=DatabaseRepository(path)
    assert r.install(snapshots)
    assert (tmp_path/'old.sqlite.bak').read_bytes()==before
    assert r.metadata()['schema_version']==2

def test_lock_and_failed_fetch(repo):
    class BrokenSource:
        def fetch(self,endpoint): raise TimeoutError('network')
    before=repo.path.read_bytes()
    with pytest.raises(TimeoutError): IngestionPipeline(repo,BrokenSource()).run()
    assert repo.path.read_bytes()==before and not repo.path.with_suffix('.sqlite.lock').exists()
    with UpdateLock(repo.path):
        with pytest.raises(RuntimeError):
            with UpdateLock(repo.path): pass

def test_pagination_detects_wrong_offset():
    class FakeHTTP:
        def get(self,*args): return {'laureates':[{'id':'1'}],'meta':{'offset':1,'count':1}}
    with pytest.raises(ValueError,match='offset'): NobelClient(FakeHTTP()).fetch('laureates')

def test_wikidata_geo_fallback_does_not_overwrite():
    p=Place.from_api({'cityNow':{'en':'Town','sameAs':['https://www.wikidata.org/wiki/Q8']}})
    cache={'Q8':{'data':{'claims':{'P625':[{'mainsnak':{'datavalue':{'value':{'latitude':1,'longitude':2,'globe':'http://www.wikidata.org/entity/Q2'}}}}]}}}}
    assert place_fields(p,cache=cache)['coord_source']=='Wikidata:Q8'
    p.point=GeoPoint(0,0)
    assert place_fields(p,cache=cache)['lat']==0
    assert place_fields(p,cache=cache)['coord_source']=='Nobel API'

def test_retry_after_is_respected():
    assert PoliteHTTP.retry_delay('45',0)==45
    assert PoliteHTTP.retry_delay(None,3)==8

def test_wikidata_cache_and_linked_entities(repo,snapshots,monkeypatch):
    from datetime import datetime, timezone
    monkeypatch.setenv('NOBEL_USER_AGENT','Test client; no real HTTP calls')
    class FakeWikidata:
        def __init__(self): self.calls=[]
        def fetch(self,ids):
            self.calls.append(list(ids))
            return {q:{'id':q,'labels':{'ru':{'value':'Пример'}},'claims':(
                {'P69':[{'rank':'normal','mainsnak':{'datavalue':{'value':{'id':'Q2'}}},'qualifiers':{'P580':[]}}]}
                if q=='Q1' else {})} for q in ids}
    client=FakeWikidata(); pipeline=IngestionPipeline(repo,wikidata=client)
    cache=pipeline.enrich(snapshots,{},90)
    assert set(cache)=={'Q1','Q2'}
    assert client.calls==[['Q1'],['Q2']]
    client.calls=[]
    again=pipeline.enrich(snapshots,cache,90)
    assert again==cache and all(not batch for batch in client.calls)
    assert repo.install(snapshots,cache)
    assert repo.wikidata_cache()['Q1']['data']['claims']['P69'][0]['qualifiers']=={'P580':[]}

def test_http_maxlag_and_retry_after(monkeypatch):
    import urllib.request,urllib.error,json
    import nobel.sources as module
    sleeps=[]
    monkeypatch.setattr(module.time,'sleep',lambda delay:sleeps.append(delay))
    calls=[]
    class Reply:
        def __enter__(self): return self
        def __exit__(self,*args): pass
        def read(self): return json.dumps({'ok':True}).encode()
    def open_request(request,timeout):
        calls.append(request)
        if len(calls)==1:
            raise urllib.error.HTTPError(request.full_url,429,'busy',{'Retry-After':'12'},None)
        return Reply()
    monkeypatch.setattr(urllib.request,'urlopen',open_request)
    assert PoliteHTTP().get('https://example.invalid',{})=={'ok':True}
    assert 12 in sleeps and len(calls)==2


def test_incomplete_wikidata_batch_rejected():
    from nobel.sources import WikidataClient
    class FakeHTTP:
        def get(self,*args):return {'entities':{}}
    with pytest.raises(ValueError,match='Incomplete'):WikidataClient(FakeHTTP()).fetch(['Q1'])


def test_batch_export_matches_individual_records(repo):
    ids=['3','1','2','1']
    result=repo.raw_laureates(ids)
    assert result==[repo.raw_laureate(i) for i in ['1','2','3']]
    assert repo.raw_laureates([])==[]
    assert repo.raw_laureates(['missing'])==[]
