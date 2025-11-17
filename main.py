# main.py
import os # <--- ADICIONE ESTA LINHA
from fastapi import FastAPI, Depends, HTTPException, status, Request
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.base import BaseHTTPMiddleware
from pydantic import BaseModel, Field
from datetime import datetime, timedelta
from typing import Optional, List, Dict
import jwt
from passlib.context import CryptContext
from firebase_admin_config import db
from orchestrator import Orchestrator
import time
import asyncio
import logging

# --- Configurações Básicas ---
app = FastAPI(title="BIA Backend API")
orchestrator = Orchestrator()
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/login")

# --- Segurança: JWT ---
SECRET_KEY = os.environ.get("SECRET_KEY", "SUA_CHAVE_SECRETA_PADRAO") # Use variável de ambiente em produção!
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

# --- Segurança: CORS ---
# Permitir todas as origens para o piloto. Restringir em produção!
origins = ["*"] 
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
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
        
        # Limpar logs antigos e contar requisições
        if client_ip in IP_REQUEST_LOGS:
            IP_REQUEST_LOGS[client_ip] = [t for t in IP_REQUEST_LOGS[client_ip] if t > current_time - RATE_WINDOW]
            if len(IP_REQUEST_LOGS[client_ip]) >= RATE_LIMIT:
                raise HTTPException(
                    status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                    detail="Rate limit exceeded. Try again later."
                )
            IP_REQUEST_LOGS[client_ip].append(current_time)
        else:
            IP_REQUEST_LOGS[client_ip] = [current_time]
            
        response = await call_next(request)
        return response

app.add_middleware(RateLimitMiddleware)


# --- Schemas Pydantic ---

class UserSchema(BaseModel):
    email: str
    password: str
    
class VitalsSchema(BaseModel):
    """Schema para vitals como sleep, hrv, steps."""
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    value: float
    unit: str
    
class BloodPressureSchema(BaseModel):
    """Schema para blood_pressure (manual)."""
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    systolic: int
    diastolic: int
    unit: str = "mmHg"

class GlucoseSchema(BaseModel):
    """Schema para glucose (manual)."""
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    value: float
    unit: str = "mg/dL"

class TherapyRegisterSchema(BaseModel):
    """Schema para registro de terapias (40Hz, neuromodulação, etc.)."""
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    therapy_type: str
    duration_min: int
    parameters: Optional[Dict] = None # Ex: {"frequency": 40, "intensity": "low"}
    notes: Optional[str] = None

class ExamUploadSchema(BaseModel):
    """Schema de registro de upload de exames. O upload real de arquivos é complexo."""
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    exam_type: str # Ex: "blood_test", "moca_score", "eeg_pdf"
    file_url: Optional[str] = None # Placeholder para URL do S3/Blob Storage
    key_values: Optional[Dict] = None # Ex: {"hba1c": 5.8, "pcr": 1.2}

class InsightSchema(BaseModel):
    """Schema de retorno para insights."""
    id: str
    type: str
    title: str
    description: str
    created_at: str 


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
        "role": "patient" # Definindo role básica
    })
    
    access_token = create_access_token(data={"sub": user.email, "role": "patient"})
    return {"access_token": access_token, "token_type": "bearer", "user_id": user.email}

@app.post("/auth/login")
async def login(form_data: OAuth2PasswordRequestForm = Depends()):
    user_doc = db.collection('users').document(form_data.username).get()
    if not user_doc.exists:
        raise HTTPException(status_code=400, detail="Incorrect email or password")
    
    user_data = user_doc.to_dict()
    if not verify_password(form_data.password, user_data['hashed_password']):
        raise HTTPException(status_code=400, detail="Incorrect email or password")

    role = user_data.get("role", "patient")
    access_token = create_access_token(data={"sub": form_data.username, "role": role})
    return {"access_token": access_token, "token_type": "bearer", "user_id": form_data.username}


# --- Funções Comuns de Ingestão e Orquestração ---

def _register_data_and_orchestrate(user_id: str, vital_type: str, data: BaseModel, collection_name: str = 'vitals'):
    """Função genérica para registrar dados, salvar logs e disparar o Orchestrator."""
    try:
        # 1. Preparar dados
        data_dict = data.model_dump()
        data_dict['user_id'] = user_id
        
        # Converter datetime para string ISO 8601 para salvar no Firestore/passar para Orchestrator
        data_dict['timestamp'] = data_dict['timestamp'].isoformat() 
        
        # 2. Gravar no Firestore
        doc_ref, doc_id = db.collection(collection_name).document(user_id).collection(vital_type).add(data_dict)
        
        # 3. Disparar o Orchestrator de forma não bloqueante
        # A API retorna a resposta rápida enquanto a análise é feita em background
        asyncio.create_task(orchestrator.process_vitals_and_generate_insights(user_id, vital_type, data_dict))
        
        return {"message": f"{vital_type} registered and processing started", "id": doc_id}
    except Exception as e:
        # Grava logs de erro
        db.collection('logs').add({"user_id": user_id, "error": str(e), "route": f"/{collection_name}/{vital_type}", "time": datetime.utcnow().isoformat()})
        logging.error(f"Error registering data for {vital_type}: {e}")
        raise HTTPException(status_code=500, detail=f"Internal Server Error: {e}")


# --- Rotas: Vitals (Automático/Wearable) ---

@app.post("/vitals/sleep", status_code=status.HTTP_201_CREATED)
async def vitals_sleep(data: VitalsSchema, user_id: str = Depends(get_current_user)):
    return _register_data_and_orchestrate(user_id, "sleep", data)

@app.post("/vitals/hrv", status_code=status.HTTP_201_CREATED)
async def vitals_hrv(data: VitalsSchema, user_id: str = Depends(get_current_user)):
    return _register_data_and_orchestrate(user_id, "hrv", data)

@app.post("/vitals/steps", status_code=status.HTTP_201_CREATED)
async def vitals_steps(data: VitalsSchema, user_id: str = Depends(get_current_user)):
    return _register_data_and_orchestrate(user_id, "steps", data)


# --- Rotas: Manual (Entrada Manual) ---

@app.post("/manual/blood_pressure", status_code=status.HTTP_201_CREATED)
async def manual_blood_pressure(data: BloodPressureSchema, user_id: str = Depends(get_current_user)):
    return _register_data_and_orchestrate(user_id, "blood_pressure", data)

@app.post("/manual/glucose", status_code=status.HTTP_201_CREATED)
async def manual_glucose(data: GlucoseSchema, user_id: str = Depends(get_current_user)):
    return _register_data_and_orchestrate(user_id, "glucose", data)


# --- Rotas: Therapy/Exams (Entrada Manual ou Programática) ---

@app.post("/therapy/register", status_code=status.HTTP_201_CREATED)
async def therapy_register(data: TherapyRegisterSchema, user_id: str = Depends(get_current_user)):
    # As terapias também podem ser analisadas pelo orchestrator, por isso usamos a mesma função
    return _register_data_and_orchestrate(user_id, "session", data, collection_name='therapies')

@app.post("/exams/upload", status_code=status.HTTP_201_CREATED)
async def exams_upload(data: ExamUploadSchema, user_id: str = Depends(get_current_user)):
    # O registro de exames não dispara ML/Orquestração de vitals, mas salva o registro
    try:
        exam_data = data.model_dump()
        exam_data['user_id'] = user_id
        exam_data['timestamp'] = exam_data['timestamp'].isoformat()
        
        # Salva o registro na coleção 'exams'
        doc_ref, doc_id = db.collection('exams').document(user_id).collection('records').add(exam_data)
        
        # Opcional: Aqui poderia disparar uma análise de correlação Exame vs Tendência
        
        return {"message": f"Exam record {data.exam_type} registered", "id": doc_id}
    except Exception as e:
        db.collection('logs').add({"user_id": user_id, "error": str(e), "route": "/exams/upload", "time": datetime.utcnow().isoformat()})
        raise HTTPException(status_code=500, detail=f"Internal Server Error: {e}")


# --- Rotas: Insights (Leitura) ---

@app.get("/insights/list", response_model=List[InsightSchema])
async def insights_list(user_id: str = Depends(get_current_user)):
    """Retorna a lista de insights gerados pelo Orchestrator/ML Engine."""
    # Buscar insights do Firestore e ordenar pelo mais recente
    insights_ref = db.collection('insights').document(user_id).collection('list').order_by('created_at', direction='DESCENDING').limit(20)
    docs = insights_ref.stream()
    
    insights = []
    for doc in docs:
        data = doc.to_dict()
        insights.append(InsightSchema(
            id=doc.id,
            type=data.get('type', 'info'),
            title=data.get('title', 'No Title'),
            description=data.get('description', 'No Description'),
            created_at=data.get('created_at', datetime.utcnow().isoformat())
        ))
    
    return insights

# --- Configuração de Deploy para Render / Uvicorn ---
# O Render usará o Uvicorn para rodar este arquivo via 'uvicorn main:app --host 0.0.0.0 --port 10000'
if __name__ == "__main__":
    import uvicorn
    # Para teste local:
    uvicorn.run(app, host="0.0.0.0", port=8000)
