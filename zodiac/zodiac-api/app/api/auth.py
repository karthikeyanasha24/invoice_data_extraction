from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.orm import Session
from datetime import datetime, timedelta
from typing import Optional
from jose import JWTError, jwt
import os
from dotenv import load_dotenv

from ..database import get_db
from ..models.user import ZodiacUser, verify_password, get_password_hash
from ..schemas.user import UserCreate, UserLogin, ZodiacUser as UserSchema, AuthResponse

load_dotenv()

router = APIRouter(prefix="/user/auth", tags=["authentication"])
security = HTTPBearer()

# JWT settings
SECRET_KEY = os.getenv("SECRET_KEY", "your-secret-key-here-change-in-production")
ALGORITHM = os.getenv("ALGORITHM", "HS256")
ACCESS_TOKEN_EXPIRE_MINUTES = 30

def create_access_token(data: dict, expires_delta: Optional[timedelta] = None):
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.utcnow() + expires_delta
    else:
        expire = datetime.utcnow() + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
    return encoded_jwt

def get_current_user(credentials: HTTPAuthorizationCredentials = Depends(security), db: Session = Depends(get_db)):
    try:
        token = credentials.credentials
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        user_id: str = payload.get("sub")
        if user_id is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Could not validate credentials",
                headers={"WWW-Authenticate": "Bearer"},
            )
    except JWTError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Could not validate credentials",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    user = db.query(ZodiacUser).filter(ZodiacUser.id == int(user_id)).first()
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return user

def get_current_user_optional(credentials: Optional[HTTPAuthorizationCredentials] = Depends(HTTPBearer(auto_error=False)), db: Session = Depends(get_db)):
    """Optional JWT authentication - returns None if no valid token provided"""
    if not credentials:
        return None
    
    try:
        token = credentials.credentials
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        user_id: str = payload.get("sub")
        if user_id is None:
            return None
    except JWTError:
        return None
    
    user = db.query(ZodiacUser).filter(ZodiacUser.id == int(user_id)).first()
    return user

@router.post("/create-user", response_model=AuthResponse)
def create_user(user: UserCreate, db: Session = Depends(get_db)):
    """Create a new user account"""
    # Check if user already exists
    db_user = db.query(ZodiacUser).filter(
        (ZodiacUser.email == user.email) | (ZodiacUser.username == user.username)
    ).first()
    if db_user:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Email or username already registered"
        )
    
    # Create new user
    hashed_password = get_password_hash(user.password)
    db_user = ZodiacUser(
        email=user.email,
        username=user.username,
        password_hash=hashed_password
    )
    db.add(db_user)
    db.commit()
    db.refresh(db_user)
    
    # Create access token
    access_token_expires = timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    access_token = create_access_token(
        data={"sub": str(db_user.id)}, expires_delta=access_token_expires
    )
    
    return AuthResponse(
        access_token=access_token,
        token_type="bearer",
        user=UserSchema.from_orm(db_user)
    )

@router.post("/login", response_model=AuthResponse)
def login(user_credentials: UserLogin, db: Session = Depends(get_db)):
    """Login user and return access token"""
    # Find user by email
    user = db.query(ZodiacUser).filter(ZodiacUser.email == user_credentials.email).first()
    if not user or not verify_password(user_credentials.password, user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Inactive user"
        )
    
    # Create access token
    access_token_expires = timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    access_token = create_access_token(
        data={"sub": str(user.id)}, expires_delta=access_token_expires
    )
    
    return AuthResponse(
        access_token=access_token,
        token_type="bearer",
        user=UserSchema.from_orm(user)
    )

@router.get("/fetch_user", response_model=UserSchema)
def fetch_user(current_user: ZodiacUser = Depends(get_current_user)):
    """Get current user information"""
    return UserSchema.from_orm(current_user)
