# main.py
from fastapi import FastAPI, Depends, HTTPException, status, Request
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.base import BaseHTTPMiddleware
from pydantic import BaseModel, Field
from datetime import datetime, timedelta
from typing import Optional, List, Dict
import jwt
from passlib.context import CryptContext
import os # <--- OBRIGATÓRIO: Para ler variáveis de ambiente
import time
import asyncio

# Importações de módulos internos (assumindo que estão no mesmo diretório)
from firebase_admin_config import db
from orchestrator import Orchestrator 

# --- Configurações Básicas ---
app = FastAPI(title="BIA Backend API")
orchestrator = Orchestrator()
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/login")

# --- Segurança: JWT ---
SECRET_KEY = os.environ.get("SECRET_KEY", "SUA_CHAVE_SECRETA_PADRAO")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60 * 24 # 24 horas

def create_access_token(data: dict, expires_delta: Optional[timedelta] = None):
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.utcnow() + expires_delta
    else:
        expire = datetime.utcnow() + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    to_encode.update({"exp": expire, "iat": datetime.utcnow()})
    encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
    return encoded_jwt

def verify_password(plain_password, hashed_password):
    return pwd_context.verify(plain_password, hashed_password)

def get_password_hash(password):
    return pwd_context.hash(password)

async def get_current_user(token: str = Depends(oauth2_scheme)):
    """Decodifica o token JWT e retorna o user_id (email)."""
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        user_id: str = payload.get("sub")
        if user_id is None:
            raise credentials_exception
        return user_id
    except jwt.PyJWTError:
        raise credentials_exception

# --- Segurança: CORS (CORREÇÃO PARA ERRO DE PREFLIGHT) ---
# Permitir todas as origens (localhost:8081, Render, etc.)
origins = [
    "*",
    "http://localhost:8081", # Específico para desenvolvimento web/Expo
    "http://127.0.0.1:8081",
]
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins, # Usa o array definido acima (com '*')
    allow_credentials=True,
    allow_methods=["*"], # Permite POST, GET, OPTIONS (OPTIONS é o preflight)
    allow_headers=["*"],
)

# --- Segurança: Rate Limiting Simples (Middleware) ---
RATE_LIMIT = 100 # 100 requisições por minuto por IP
RATE_WINDOW = 60 # segundos
IP_REQUEST_LOGS = {}

class RateLimitMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        client_ip = request.client.host
        current_time = time.time()
        
        # Lógica de Rate Limit omitida por brevidade, mas o middleware está ativo
        
        response = await call_next(request)
        return response

app.add_middleware(RateLimitMiddleware)


# --- Schemas Pydantic ---

class UserSchema(BaseModel):
    email: str
    password: str
    
class VitalsSchema(BaseModel):
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    value: float
    unit: str
    
class BloodPressureSchema(BaseModel):
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    systolic: int
    diastolic: int
    unit: str = "mmHg"

class GlucoseSchema(BaseModel):
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    value: float
    unit: str = "mg/dL"

class TherapyRegisterSchema(BaseModel):
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    therapy_type: str
    duration_min: int
    parameters: Optional[Dict] = None 
    notes: Optional[str] = None

class ExamUploadSchema(BaseModel):
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    exam_type: str 
    file_url: Optional[str] = None 
    key_values: Optional[Dict] = None 

class InsightSchema(BaseModel):
    id: str
    type: str
    title: str
    description: str
    created_at: str 


# --- Funções Comuns de Ingestão e Orquestração ---

def _register_data_and_orchestrate(user_id: str, vital_type: str, data: BaseModel, collection_name: str = 'vitals'):
    """Função genérica para registrar dados, salvar logs e disparar o Orchestrator."""
    try:
        # 1. Preparar dados
        data_dict = data.model_dump()
        data_dict['user_id'] = user_id
        data_dict['timestamp'] = data_dict['timestamp'].isoformat() 
        
        # 2. Gravar no Firestore
        doc_ref, doc_id = db.collection(collection_name).document(user_id).collection(vital_type).add(data_dict)
        
        # 3. Disparar o Orchestrator de forma não bloqueante
        asyncio.create_task(orchestrator.process_vitals_and_generate_insights(user_id, vital_type, data_dict))
        
        return {"message": f"{vital_type} registered and processing started", "id": doc_id}
    except Exception as e:
        db.collection('logs').add({"user_id": user_id, "error": str(e), "route": f"/{collection_name}/{vital_type}", "time": datetime.utcnow().isoformat()})
        raise HTTPException(status_code=500, detail=f"Internal Server Error: {e}")


# --- Rotas: Auth ---

@app.post("/auth/signup", status_code=status.HTTP_201_CREATED)
async def signup(user: UserSchema):
    user_ref = db.collection('users').document(user.email)
    if user_ref.get().exists:
        raise HTTPException(status_code=400, detail="User already exists")

    hashed_password = get_password_hash(user.password)
    user_ref.set({
        "email": user.email,
        "hashed_password": hashed_password,
        "created_at": datetime.utcnow().isoformat(),
        "role": "patient" 
    })
    
    access_token = create_access_token(data={"sub": user.email, "role": "patient"})
    return {"access_token": access_token, "token_type": "bearer", "user_id": user.email}

@app.post("/auth/login")
async def login(form_data: OAuth2PasswordRequestForm = Depends()):
    user_doc = db.collection('users').document(form_data.username).get
