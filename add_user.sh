#!/bin/bash
# Insert new user: vulgansaran@gmail.com / barangan
docker exec tahrix-postgres-1 psql -U tahrix -d tahrix -c "
INSERT INTO users (id, email, hashed_password, is_active, created_at)
VALUES (
  gen_random_uuid(),
  'vulgansaran@gmail.com',
  '\$2b\$12\$LQv3c1yqBWVHxkd0LHAkCOYz6TtxMQJqhN8/LewY5eWvqZYxCqF2e',  -- barangan (bcrypt hash)
  true,
  NOW()
) ON CONFLICT (email) DO NOTHING;
"