import os
import json
import time
import boto3
import requests
from uuid import uuid4
import streamlit as st
from dotenv import load_dotenv
from botocore.exceptions import NoCredentialsError, ClientError, EndpointConnectionError
from botocore.config import Config

load_dotenv()

# ----------------- Config -----------------
POD_ID = os.getenv("POD_ID", "i1q8dnudt5raii")
BACKEND_PORT = "8000"
BACKEND_URL = f"https://{POD_ID}-{BACKEND_PORT}.proxy.runpod.net/"

BUCKET_NAME = os.getenv("BUCKET_NAME", "rag-teste-bnu")
S3_ENDPOINT = os.getenv("S3_ENDPOINT")  # deixe vazio/nulo para AWS S3 oficial
AWS_REGION = os.getenv("AWS_REGION", "us-east-1")
AWS_ACCESS_KEY_ID = os.getenv("AWS_ACCESS_KEY_ID")
AWS_SECRET_ACCESS_KEY = os.getenv("AWS_SECRET_ACCESS_KEY")
AWS_SESSION_TOKEN = os.getenv("AWS_SESSION_TOKEN")  # opcional (credenciais temporárias)
PREFIX_BASE = "uploads"

def s3_safe_key(name: str) -> str:
    ext = ""
    if "." in name:
        ext = "." + name.split(".")[-1]
    return f"{uuid4().hex}{ext}"

def check_health_server() -> bool:
    try:
        resp = requests.get(f"{BACKEND_URL}/health", timeout=10)
        return resp.status_code == 200
    except requests.RequestException:
        return False

# Cliente S3
session_kwargs = dict(
    aws_access_key_id=AWS_ACCESS_KEY_ID,
    aws_secret_access_key=AWS_SECRET_ACCESS_KEY,
    region_name=AWS_REGION,
)
if AWS_SESSION_TOKEN:
    session_kwargs["aws_session_token"] = AWS_SESSION_TOKEN

s3 = boto3.client(
    "s3",
    endpoint_url=S3_ENDPOINT or None,
    config=Config(signature_version="s3v4", retries={"max_attempts": 3, "mode": "standard"}),
    **session_kwargs
)

def check_s3_access() -> tuple[bool, str]:
    """
    Verifica se o bucket é acessível e credenciais estão ok.
    """
    try:
        s3.head_bucket(Bucket=BUCKET_NAME)
        return True, "Acesso ao bucket OK."
    except NoCredentialsError:
        return False, "Credenciais AWS ausentes."
    except EndpointConnectionError as e:
        return False, f"Falha ao conectar no endpoint S3 ({S3_ENDPOINT or 'AWS padrão'}): {e}"
    except ClientError as e:
        # Mensagens úteis: 403 (AccessDenied), 404 (Not Found) etc.
        return False, f"ClientError ao acessar bucket: {e.response.get('Error', {})}"
    except Exception as e:
        return False, f"Erro inesperado no S3: {e}"

def perguntar_backend(pergunta: str, k: int = 4, namespace: str | None = None, documentos: list | None = None) -> dict:
    """
    Envia a pergunta ao backend Flask (rota /chat) e retorna o JSON de resposta.
    A rota /chat aceita: {"question": "...", "k": int, "namespace": str?, "documents": list?}
    """
    if not pergunta or not pergunta.strip():
        return {"ok": False, "error": "Pergunta vazia."}

    payload = {"question": pergunta.strip(), "k": k}
    if namespace:
        payload["namespace"] = namespace
    if documentos:
        payload["documents"] = documentos

    try:
        resp = requests.post(f"{BACKEND_URL}/chat", json=payload, timeout=300)
        resp.raise_for_status()
        try:
            data = resp.json()
        except ValueError:
            data = {"raw": resp.text}
        return {"ok": True, "data": data}
    except requests.HTTPError as e:
        msg = e.response.text if e.response is not None else str(e)
        return {"ok": False, "error": f"HTTP {getattr(e.response, 'status_code', '?')}: {msg}"}
    except requests.RequestException as e:
        return {"ok": False, "error": f"Falha de conexão com o backend: {e}"}

# ----------------- UI -----------------
st.set_page_config(page_title="Unimed chat AI", page_icon="💬", layout="centered")
st.title("Assistente de Chat")

footer_placeholder = st.empty()

with st.sidebar:
    with st.expander("Server"):
        if st.button("Verificar Servidor de IA", use_container_width=True):
            ok = check_health_server()
            placeholder = st.empty()
            if ok:
                placeholder.success("Servidor OK ✅")
            else:
                placeholder.error("Servidor Indisponível ❌")
            time.sleep(5)
            placeholder.empty()

    with st.expander("Inserir novos arquivos", expanded=True):
        uploaded_files = st.file_uploader("Adicionar arquivo(s):", type=['pdf'], accept_multiple_files=True)

        # Teste rápido do S3 (opcional, mas ajuda MUITO a diagnosticar)
        if st.button("Testar acesso ao S3", use_container_width=True):
            ok, msg = check_s3_access()
            if ok:
                st.success(msg) 
            else: 
                st.error(msg)

        col1, col2 = st.columns([2,2])
        with col1:
            if st.button("Enviar para S3", use_container_width=True):
                if not uploaded_files:
                    st.warning("Nenhum arquivo selecionado.")
                else:
                    enviados: list[str] = []
                    falhas: list[tuple[str, str]] = []

                    for f in uploaded_files:
                        progress = st.progress(0)
                        status = st.empty()

                        key = f"{PREFIX_BASE}/{s3_safe_key(f.name)}"
                        try:
                            f.seek(0)  # garante ponteiro no início
                            s3.upload_fileobj(
                                f,
                                BUCKET_NAME,
                                key,
                                ExtraArgs={"ContentType": "application/pdf"},
                            )
                            progress.progress(100)
                            status.text("Concluído ✅")
                            st.success(f"✅ Enviado: s3://{BUCKET_NAME}/{key}")
                            enviados.append(key)

                        except NoCredentialsError:
                            progress.empty()
                            status.empty()
                            falhas.append((f.name, "NoCredentialsError (credenciais ausentes)"))
                            st.error("⚠️ Credenciais da AWS não disponíveis.")
                        except EndpointConnectionError as error:
                            progress.empty()
                            status.empty()
                            falhas.append((f.name, f"EndpointConnectionError: {error}"))
                            st.error(f"🌐 Falha de conexão com o endpoint S3: {error}")
                        except ClientError as error:
                            progress.empty()
                            status.empty()
                            err = error.response.get("Error", {})
                            falhas.append((f.name, f"{err.get('Code')} - {err.get('Message')}"))
                            st.error(f"❌ Erro do cliente S3 ao enviar {f.name}: {err}")
                        except Exception as error:
                            progress.empty()
                            status.empty()
                            falhas.append((f.name, str(error)))
                            st.error(f"❌ Erro ao enviar {f.name}: {error}")

                    # Resumo
                    if enviados:
                        st.info("Arquivos enviados com sucesso:")
                        for k_ in enviados:
                            st.write(f"- s3://{BUCKET_NAME}/{k_}")
                    if falhas:
                        st.warning("Falhas:")
                        for nome, motivo in falhas:
                            st.write(f"- {nome}: {motivo}")

        with col2:
            if st.button("Atualizar base de conhecimento", use_container_width=True):
                pass

    with st.expander("Opções avançadas", expanded=False):
        k = st.slider("k (nº de documentos)", min_value=1, max_value=10, value=4, step=1)
        namespace = st.text_input("Namespace (opcional):", value="")
        docs_json = st.text_area("Documentos (JSON)", placeholder='[{"id":"1","text":"...","metadata":{}}]')

pergunta = st.text_area("Pergunta:", placeholder="Digite sua pergunta aqui...", height=100)

if st.button("Enviar"):
    documentos = None

    if docs_json.strip():
        try:
            documentos = json.loads(docs_json)
        except Exception as error:
            st.warning(f"Documentos inválidos: {error}")

    with st.spinner("Consultando os documentos..."):
        resposta = perguntar_backend(
            pergunta=pergunta,
            k=k,
            namespace=namespace or None, documentos=documentos
            )
    
    if resposta["ok"]:
        data = resposta["data"]
        answer = data.get("answer") or data.get("resposta") or data.get("raw") or data
        fontes = data.get("sources") or data.get("fontes")

        st.markdown("### Resposta:")
        if isinstance(answer, (dict, list)):
            st.json(answer)
        else:
            st.write(answer)

        
        if fontes:
            st.markdown("### Fontes:")
            st.json(fontes)

    else:
        st.error(resposta["error"])


# -------------------------------------------------
with footer_placeholder.container():
    st.markdown("""
    <style>
    .fixed-footer {
        position: fixed;
        left: 0;
        bottom: 0;
        width: 100%;
        background-color: #f1f1f1;
        color: #333;
        text-align: center;
        padding: 10px;
        box-shadow: 0 -2px 5px rgba(0,0,0,0.1);
    }
    </style>
    <div class="fixed-footer">
        Mensagem de rodapé
    </div>
    """, unsafe_allow_html=True)
