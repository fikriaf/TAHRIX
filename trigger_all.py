import sys
sys.path.insert(0, '/app')
from app.workers.tasks import run_investigation

case_ids = [
    '676aa07f-c117-4fa1-9a09-8d4364f0e874',
    'f788e6cb-c11b-405a-89a9-e018def4212e',
    '07914de9-86c8-4835-8519-4b26465ab5b8',
    'ff7ddbb7-c1fd-4ffb-80f6-ae075d0048c1'
]

for cid in case_ids:
    result = run_investigation.apply_async(args=[cid])
    print(f'Dispatched {cid}')