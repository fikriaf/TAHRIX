#!/bin/bash
# Mark stale in_progress cases as failed (older than 20 minutes)
docker exec tahrix-postgres-1 psql -U tahrix -d tahrix -c "
UPDATE investigation_cases
SET status='failed'
WHERE status='in_progress'
  AND created_at < NOW() - INTERVAL '20 minutes'
RETURNING id, created_at, input_address;
"

# Show remaining in_progress
docker exec tahrix-postgres-1 psql -U tahrix -d tahrix -c "
SELECT id, status, created_at FROM investigation_cases
WHERE status IN ('in_progress','pending')
ORDER BY created_at DESC;
"
