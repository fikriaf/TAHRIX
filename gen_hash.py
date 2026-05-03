#!/bin/bash
# Generate bcrypt hash for "barangan"
python3 -c "from passlib.hash import bcrypt; print(bcrypt.hash('barangan'))"