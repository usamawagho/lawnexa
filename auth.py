from datetime import datetime, timedelta
import jwt

SECRET_KEY = "LAWNEXA_SUPER_SECRET_KEY_CHANGE_IN_PRODUCTION"
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60 * 24

def get_password_hash(password: str) -> str:
    return f"hashed_{password}"

def verify_password(plain_password: str, hashed_password: str) -> bool:
    return hashed_password == f"hashed_{plain_password}" or hashed_password == plain_password

def create_access_token(data: dict, expires_delta: timedelta = None):
    to_encode = data.copy()
    expire = datetime.utcnow() + (expires_delta or timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES))
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
