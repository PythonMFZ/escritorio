"""Base comum dos testes: banco SQLite temporário, API do Claude simulada e helpers de login.

Uso (no topo de cada teste, ANTES de importar o app):
    from _base import preparar, check, FAIL, fim
    A, c = preparar(handler=None)   # handler opcional: função(request) -> httpx2.Response
"""
import json
import os
import sys
import tempfile

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FAIL = []


def check(cond, msg):
    print(("  OK   " if cond else "  FAIL ") + msg)
    if not cond:
        FAIL.append(msg)


def resposta_texto(texto="Feito.", model="claude-opus-5-5"):
    import httpx2
    return httpx2.Response(200, json={"id": "m", "type": "message", "role": "assistant", "model": model,
                                      "content": [{"type": "text", "text": texto}], "stop_reason": "end_turn",
                                      "stop_sequence": None, "usage": {"input_tokens": 100, "output_tokens": 50}})


def preparar(handler=None, env=None):
    """Isola o teste num diretório temporário, importa o app e troca o cliente do Claude por um simulado."""
    tmp = tempfile.mkdtemp(prefix="escritorio-teste-")
    os.environ.update({
        "DATABASE_URL": "sqlite:///" + os.path.join(tmp, "teste.db"),
        "DISABLE_LOCAL_WHISPER": "1",
        "ANTHROPIC_API_KEY": "sk-test",
        "SESSION_SECRET": "teste",
        "UPLOAD_DIR": os.path.join(tmp, "uploads"),
        "AUDIO_UPLOAD_DIR": os.path.join(tmp, "audios"),
        "ROTINAS_LOCK_FILE": os.path.join(tmp, "rotinas.lock"),
        **(env or {}),
    })
    sys.path.insert(0, RAIZ)
    os.chdir(RAIZ)
    import anthropic
    import httpx2
    import app as A
    if handler is None:
        def handler(request):
            return resposta_texto(model=json.loads(request.content).get("model", "claude-opus-5-5"))
    A._pr_client_cache["c"] = anthropic.Anthropic(
        api_key="sk-test", max_retries=0, http_client=anthropic.DefaultHttpxClient(transport=httpx2.MockTransport(handler)))
    from fastapi.testclient import TestClient
    c = TestClient(A.app, base_url="https://testserver")
    c.__enter__()
    return A, c


def criar_empresa(A, usuarios=(("admin", "Rafael", "admin@t.com"), ("equipe", "Ana", "ana@t.com"))):
    from sqlmodel import Session
    with Session(A.engine) as s:
        co = A.Company(name="Maffezzolli Capital")
        s.add(co)
        s.commit()
        s.refresh(co)
        ids = {}
        for papel, nome, email in usuarios:
            u = A.User(name=nome, email=email, password_hash=A.hash_password("senha123"))
            s.add(u)
            s.commit()
            s.refresh(u)
            s.add(A.Membership(user_id=u.id, company_id=co.id, role=papel))
            ids[papel] = u.id
        s.commit()
        return co.id, ids


def login(c, email):
    c.cookies.clear()
    r = c.post("/login", data={"email": email, "password": "senha123"}, follow_redirects=False)
    assert r.status_code == 303, f"login falhou para {email}"


def esperar_chamado(c, chamado_id, timeout=30):
    import time
    fim_ = time.time() + timeout
    d = {}
    while time.time() < fim_:
        d = c.get(f"/predio/chamados/{chamado_id}/status").json()
        if not d.get("em_andamento"):
            return d
        time.sleep(0.2)
    return d


def fim():
    print("\nFALHAS:", FAIL or "nenhuma")
    sys.exit(1 if FAIL else 0)
