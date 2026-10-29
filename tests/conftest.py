import copy
import pytest
from nobel.storage import DatabaseRepository

@pytest.fixture
def snapshots():
    def place(city,country,lat,lon):
        return {'city':{'en':city},'country':{'en':country},'cityNow':{'en':city,'latitude':str(lat),'longitude':str(lon)},'countryNow':{'en':country}}
    def award(y,cat,portion='1',affiliations=None):
        return {'awardYear':str(y),'category':{'en':cat},'dateAwarded':f'{y}-10-01','portion':portion,
                'prizeStatus':'received','sortOrder':'1','motivation':{'en':'For <i>important</i> discoveries','se':'En text'},
                'prizeAmount':1000000,'prizeAmountAdjusted':2000000,'affiliations':affiliations or []}
    p=place('London','UK',51.5,-.12); p['name']={'en':'College A'}
    q=place('Stockholm','Sweden',59.3,18.06); q['name']={'en':'College B'}
    z=place('New York','USA',40.7,-74.0); z['name']={'en':'College C'}
    a=award(2000,'Physics','1/2',[p,q]); b=award(2010,'Chemistry','1',[z]); c=award(2020,'Peace')
    laureates=[
        {'id':'1','knownName':{'en':'Alice Example'},'fullName':{'en':'Alice X. Example'},'gender':'female',
         'birth':{'date':'1980-12-11','place':place('Zero','UK',0,0)},'wikidata':{'id':'Q1'},
         'futureField':{'nested':['KEEP',{'ru':'Сохранить'}]},'nobelPrizes':[a,b]},
        {'id':'2','knownName':{'en':'Bob Example'},'gender':'male','birth':{'date':'1900-00-00','place':{}},'nobelPrizes':[award(2000,'Physics','1/2')]},
        {'id':'3','orgName':{'en':'Peace Organization'},'founded':{'date':'1995-00-00'},'nobelPrizes':[c]}]
    prizes=[]
    for entry,ids in [(a,['1','2']),(b,['1']),(c,['3'])]:
        item=copy.deepcopy(entry); item.pop('affiliations'); item['laureates']=[{'id':i} for i in ids]; prizes.append(item)
    snapshots={}
    for endpoint,items in [('laureates',laureates),('nobelPrizes',prizes)]:
        snapshots[endpoint]={'items':items,'pages':[{endpoint:items,'meta':{'count':len(items),'offset':0,'limit':1000}}]}
    return snapshots

@pytest.fixture
def repo(tmp_path,snapshots):
    r=DatabaseRepository(tmp_path/'db.sqlite'); r.install(snapshots); return r
