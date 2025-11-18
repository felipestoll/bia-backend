import firebase_admin
from firebase_admin import credentials, firestore
import os 
import json

# --- Configuração de Credenciais ---
try:
    # 1. Tenta usar a variável de ambiente secreta do Render
    if not firebase_admin._apps:
        if os.environ.get("FIREBASE_CREDENTIALS"):
            # Carrega o JSON da variável de ambiente (CRÍTICO: o valor deve ser um JSON string válido)
            cred_json = json.loads(os.environ["FIREBASE_CREDENTIALS"])
            cred = credentials.Certificate(cred_json)
        else:
            # 2. Fallback para desenvolvimento local:
            # Este caminho só é usado se você rodar localmente e a variável não estiver definida.
            cred = credentials.Certificate("serviceAccountKey.json")
            
        firebase_admin.initialize_app(cred)
except Exception as e:
    # Lança um erro robusto se a conexão com o Firebase falhar
    # Isso fará com que o Render mostre o traceback completo, em vez de Bad Gateway
    raise RuntimeError(f"Erro Crítico ao inicializar o Firebase: {e}. Verifique FIREBASE_CREDENTIALS.")
    
# Instância do Firestore para uso global
db = firestore.client()
