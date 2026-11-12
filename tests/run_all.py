"""Roda todos os testes (cada um em processo próprio, com banco temporário) e resume.

    python tests/run_all.py            # todos
    python tests/run_all.py automacoes # só os que têm 'automacoes' no nome
"""
import os
import subprocess
import sys
import time

AQUI = os.path.dirname(os.path.abspath(__file__))


def main():
    filtro = sys.argv[1] if len(sys.argv) > 1 else ""
    testes = sorted(f for f in os.listdir(AQUI) if f.startswith("test_") and f.endswith(".py") and filtro in f)
    falhou = []
    for t in testes:
        ini = time.time()
        p = subprocess.run([sys.executable, os.path.join(AQUI, t)], capture_output=True, text=True, timeout=1200)
        linhas = p.stdout.splitlines()
        oks = sum(1 for l in linhas if l.startswith("  OK"))
        fails = [l.strip() for l in linhas if l.startswith("  FAIL")]
        status = "ok" if p.returncode == 0 else "FALHOU"
        print(f"{t:<34} {status:<7} {oks:>3} OK  {time.time() - ini:5.1f}s")
        for f in fails:
            print("    " + f)
        if p.returncode != 0:
            falhou.append(t)
            if not fails:
                print("    " + "\n    ".join((p.stderr or p.stdout).strip().splitlines()[-8:]))
    print(f"\n{len(testes) - len(falhou)}/{len(testes)} arquivos passaram.")
    sys.exit(1 if falhou else 0)


if __name__ == "__main__":
    main()
