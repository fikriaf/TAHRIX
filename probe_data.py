import urllib.request, json

login = urllib.request.Request(
    'http://localhost:8800/api/v1/auth/login', method='POST',
    data=json.dumps({'email':'smoke@tahrix.io','password':'Smoke1234!'}).encode(),
    headers={'Content-Type':'application/json'})
token = json.loads(urllib.request.urlopen(login).read())['access_token']
case_id = '3ea6de2a-f3a0-404e-a296-1b9545606379'

# Full case
req = urllib.request.Request(f'http://localhost:8800/api/v1/cases/{case_id}',
    headers={'Authorization': f'Bearer {token}'})
c = json.loads(urllib.request.urlopen(req).read())
print("=== CASE FIELDS ===")
print(json.dumps(c, indent=2))

# Events sample
req2 = urllib.request.Request(f'http://localhost:8800/api/v1/cases/{case_id}/events',
    headers={'Authorization': f'Bearer {token}'})
evs = json.loads(urllib.request.urlopen(req2).read())
print("\n=== EVENTS COUNT:", len(evs))
# Show tool names and result keys
tools_seen = {}
for ev in evs:
    tool = ev.get('tool') or ev.get('phase','')
    result = ev.get('result') or {}
    if tool and tool not in tools_seen:
        tools_seen[tool] = list(result.keys()) if isinstance(result, dict) else str(type(result))
for t,k in tools_seen.items():
    print(f"  {t}: {k}")

# Graph sample
req3 = urllib.request.Request(f'http://localhost:8800/api/v1/cases/{case_id}/graph',
    headers={'Authorization': f'Bearer {token}'})
g = json.loads(urllib.request.urlopen(req3).read())
print(f"\n=== GRAPH: {len(g.get('nodes',[]))} nodes, {len(g.get('edges',[]))} edges")
if g.get('nodes'):
    print("Node keys:", list(g['nodes'][0].keys()))
if g.get('edges'):
    print("Edge keys:", list(g['edges'][0].keys()))
