import urllib.request, json

login = urllib.request.Request(
    'http://localhost:8800/api/v1/auth/login', method='POST',
    data=json.dumps({'email':'smoke@tahrix.io','password':'Smoke1234!'}).encode(),
    headers={'Content-Type':'application/json'})
token = json.loads(urllib.request.urlopen(login).read())['access_token']
case_id = '3ea6de2a-f3a0-404e-a296-1b9545606379'

req2 = urllib.request.Request(f'http://localhost:8800/api/v1/cases/{case_id}/events',
    headers={'Authorization': f'Bearer {token}'})
evs = json.loads(urllib.request.urlopen(req2).read())

for ev in evs:
    result = ev.get('result')
    if result:
        print(f"\n=== {ev.get('tool')} result keys: {list(result.keys())[:15]}")
        # Print a compact sample
        for k,v in list(result.items())[:8]:
            print(f"  {k}: {str(v)[:120]}")
