#!/bin/bash
# Mark all current in_progress cases as failed (worker was restarted, they're orphaned)
docker exec tahrix-postgres-1 psql -U tahrix -d tahrix -c "
UPDATE investigation_cases
SET status='failed', error_message='Worker restarted — investigation was orphaned'
WHERE status='in_progress'
RETURNING id, created_at, input_address;
"

echo "=== Remaining active ==="
docker exec tahrix-postgres-1 psql -U tahrix -d tahrix -c "
SELECT id, status, created_at FROM investigation_cases
WHERE status IN ('in_progress','pending')
ORDER BY created_at;
"
