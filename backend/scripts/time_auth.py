import time
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.auth.auth import hash_password, verify_password

def main():
    start = time.time()
    hash_val = hash_password("password123")
    print(f"Hash took: {time.time() - start:.2f} seconds")

    start = time.time()
    res = verify_password("password123", hash_val)
    print(f"Verify took: {time.time() - start:.2f} seconds")

if __name__ == "__main__":
    main()
