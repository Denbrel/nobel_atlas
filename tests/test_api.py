from fastapi.testclient import TestClient
import api

def test_api(repo,monkeypatch):
    monkeypatch.setenv('NOBEL_DB',str(repo.path)); monkeypatch.delenv('NOBEL_API_KEY',raising=False)
    client=TestClient(api.app)
    assert client.get('/health').status_code==200
    assert client.get('/stats').json()['award_credits']==4
    result=client.get('/laureates?limit=1&offset=1').json()
    assert result['total']==3 and len(result['items'])==1
    assert client.get('/awards?category=Physics').json()['total']==2
    assert client.get('/laureates/1').json()['data']['futureField']['nested'][0]=='KEEP'
    assert client.get('/laureates/9999').status_code==404
    assert client.get('/awards?year_from=2020&year_to=2000').status_code==422
    assert client.get('/awards?limit=100000').status_code==422
    assert client.get('/export.csv').headers['content-type'].startswith('text/csv')
    monkeypatch.setenv('NOBEL_API_KEY','test-only-secret')
    assert client.get('/stats').status_code==401
    assert client.get('/stats',headers={'X-API-Key':'test-only-secret'}).status_code==200
    assert client.post('/update').status_code==404
