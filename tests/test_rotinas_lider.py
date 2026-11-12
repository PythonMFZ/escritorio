"""Rotinas de fundo rodam em um processo só (líder por flock); se o líder morre, outro assume."""
import os
import subprocess
import sys
import tempfile
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _base import check, fim  # noqa: E402

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
lock = os.path.join(tempfile.mkdtemp(), "rotinas.lock")
# Extrai do app.py só o trecho do líder (sem importar o app inteiro, que é pesado)
src = open(os.path.join(RAIZ, "app.py")).read()
ini, fim_ = src.index("# ── Rotinas de fundo em um processo só"), src.index("def utcnow() -> datetime:")
trecho = "import os\n" + src[ini:fim_]
codigo = trecho + (
    "\nimport sys, time\n"
    "eu = _processo_lider()\n"
    "print('LIDER' if eu else 'SEGUIDOR', flush=True)\n"
    "if not eu:\n"
    "    for _ in range(40):\n"
    "        time.sleep(0.25)\n"
    "        if _processo_lider():\n"
    "            print('ASSUMIU', flush=True); break\n"
    "time.sleep(float(sys.argv[1]))\n")
env = {**os.environ, "ROTINAS_LOCK_FILE": lock}
p1 = subprocess.Popen([sys.executable, "-c", codigo, "2"], stdout=subprocess.PIPE, text=True, env=env)
time.sleep(0.5)
p2 = subprocess.Popen([sys.executable, "-c", codigo, "0"], stdout=subprocess.PIPE, text=True, env=env)
o1, _ = p1.communicate(timeout=30)
o2, _ = p2.communicate(timeout=30)
check("LIDER" in o1.split(), "o primeiro processo vira líder")
check(o2.split()[0] == "SEGUIDOR", "o segundo não roda as rotinas enquanto o líder vive")
check("ASSUMIU" in o2, "quando o líder termina, o segundo assume")
for arq, nome in (("ui_predio.py", "_pr_agendador"), ("ui_predio_automacoes.py", "_au_agendador"),
                  ("ui_augur_doc_index.py", "_index_loop"), ("ui_cloud_storage.py", "_cs_background_loop"),
                  ("ui_backup_s3.py", "_backup_loop"), ("ui_reunioes_whisper.py", "_watchdog_reunioes_presas")):
    check(f"_so_no_lider({nome})" in open(os.path.join(RAIZ, arq)).read(), f"{nome} só no líder")
fim()
