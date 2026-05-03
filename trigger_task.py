import sys
sys.path.insert(0, '/app')
from app.workers.tasks import run_investigation

case_ids = [
    '74909617-b00f-4846-a012-9a7dc1f58e6a',
    'c5578212-6b28-4760-bc8f-1fccfab9a948'
]

for cid in case_ids:
    result = run_investigation.apply_async(args=[cid])
    print(f'Dispatched {cid}: {result.id}')