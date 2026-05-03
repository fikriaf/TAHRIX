#!/bin/bash
echo "=== smoke user hash ==="
docker exec tahrix-postgres-1 psql -U tahrix -d tahrix -t -c "SELECT hashed_password FROM users WHERE email='smoke@tahrix.io';"

echo "=== add new user ==="
# Use the same hash format as smoke user - will need to generate proper hash
docker exec tahrix-postgres-1 psql -U tahrix -d tahrix -c "
INSERT INTO users (id, email, hashed_password, is_active, created_at)
VALUES (
  gen_random_uuid(),
  'vulgansaran@gmail.com',
  '\$2b\$12\$LQv3c1yqBWVHxkd0LHAkCOYz6TtxMQJqhN8/LewY5eWvqZYxCqF2e',
  true,
  NOW()
) ON CONFLICT (email) DO NOTHING;
"