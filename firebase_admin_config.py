import firebase_admin
from firebase_admin import credentials, firestore
import os  # <--- CORREÇÃO: Módulo 'os' importado aqui
import json

# --- Configuração de Credenciais ---
try:
    # Tenta usar a variável de ambiente (necessário 'import os')
    if not firebase_admin._apps:
        if os.environ.get("FIREBASE_CREDENTIALS"):
            # Carrega credenciais de uma variável de ambiente (JSON string)
            cred_json = json.loads(os.environ["FIREBASE_CREDENTIALS"])
            cred = credentials.Certificate(cred_json)
        else:
            # Fallback para desenvolvimento local:
            cred = credentials.Certificate("serviceAccountKey.json")
            
        firebase_admin.initialize_app(cred)
except Exception as e:
    # Lança um erro robusto se a conexão falhar
    raise RuntimeError(f"Erro Crítico ao inicializar o Firebase: {e}")
    
# Instância do Firestore para uso global
db = firestore.client()
