import firebase_admin
from firebase_admin import credentials, firestore
import os
import json

# --- Configuração de Credenciais ---
# Em produção, usa-se a variável de ambiente. Para o piloto no Render,
# recomenda-se colocar o conteúdo do arquivo serviceAccountKey.json
# na variável de ambiente "FIREBASE_CREDENTIALS" para segurança.
try:
    if not firebase_admin._apps:
        if os.environ.get("FIREBASE_CREDENTIALS"):
            # Carrega credenciais de uma variável de ambiente (JSON string)
            cred_json = json.loads(os.environ["FIREBASE_CREDENTIALS"])
            cred = credentials.Certificate(cred_json)
        else:
            # Fallback para desenvolvimento local: use o arquivo.
            # Certifique-se de que 'serviceAccountKey.json' esteja no diretório raiz para testes locais.
            cred = credentials.Certificate("serviceAccountKey.json")
            
        firebase_admin.initialize_app(cred)
        # print("Firebase inicializado com sucesso.") # Desabilitar em produção para não expor logs
except Exception as e:
    # Em um serviço de backend, é melhor levantar (raise) o erro para falhar
    # o deploy se a conexão com o banco não estiver funcional.
    raise RuntimeError(f"Erro Crítico ao inicializar o Firebase: {e}")
    
# Instância do Firestore para uso global
db = firestore.client()