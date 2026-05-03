#!/bin/bash
docker exec tahrix-postgres-1 psql -U tahrix -d tahrix -c "
UPDATE investigation_cases
SET status='failed', error_message='Stale pending — never dispatched'
WHERE status='pending'
  AND created_at < NOW() - INTERVAL '1 hour'
RETURNING id;
"
