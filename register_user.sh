#!/bin/bash
RESULT=$(curl -s -X POST http://localhost:8800/api/v1/auth/register \
  -H "Content-Type: application/json" \
  -d '{"email":"vulgansaran@gmail.com","password":"barangan"}')

echo "$RESULT"