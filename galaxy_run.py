#!/usr/bin/env python3
"""
Galaxy Profile — one-shot bootstrap + generate + (optional) commit/push.

Uso típico:
  python3 galaxy_run.py --username luerfel --luerfel-config --fix-workflow --run --commit --push

O que faz:
- Detecta repo git
- Move conteúdo de subpasta *-main/*-master para a raiz (se necessário)
- Garante config.yml (copia do config.example.yml se faltar)
- Opcional: sobrescreve config.yml com um template pronto "Luerfel" (inglês)
- Garante workflow .github/workflows/generate-profile.yml (cria ou corrige)
- Cria venv, instala requirements, roda generator.main
- Opcional: git add/commit/push

Observações:
- Não cria secrets do GitHub. Token (se quiser) deve estar no Actions secrets ou exportado no terminal.
"""

import argparse
import datetime as dt
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

WORKFLOW_PATH = Path(".github/workflows/generate-profile.yml")

DEFAULT_WORKFLOW_YML = """name: Generate Profile SVGs

on:
  workflow_dispatch:
  schedule:
    - cron: "0 */12 * * *"
  push:
    paths:
      - "config.yml"
      - "generator/**"
      - ".github/workflows/generate-profile.yml"

permissions:
  contents: write

jobs:
  generate:
    runs-on: ubuntu-latest
    steps:
      - name: Checkout
        uses: actions/checkout@v4
        with:
          fetch-depth: 0

      - name: Setup Python
        uses: actions/setup-python@v5
        with:
          python-version: "3.11"

      - name: Install deps
        run: |
          python -m pip install --upgrade pip
          pip install -r requirements.txt

      - name: Generate SVGs
        run: |
          python -m generator.main

      - name: Commit generated SVGs
        run: |
          git status --porcelain
          if [ -n "$(git status --porcelain assets/generated)" ]; then
            git config user.name "github-actions[bot]"
            git config user.email "41898282+github-actions[bot]@users.noreply.github.com"
            git add assets/generated
            git commit -m "chore: update profile SVGs [skip ci]"
            git push
          else
            echo "No SVG changes to commit."
          fi
"""

def luerfel_config_yml(username: str) -> str:
    # Config em inglês e com schema correto (items:)
    return f"""# Galaxy Profile README Configuration
username: {username}

profile:
  name: "Luerfel"
  tagline: "Software Engineer • Data & AI (NLP)"
  company: "Soepia"
  location: "Campinas, SP — Brazil"
  bio: |
    Building data-driven products.
    Interested in NLP, machine learning, and automation.
  philosophy: '"Keep shipping. Keep learning."'

social:
  email: "mluerfel@gmail.com"
  linkedin: "matheus-mendonca-65ba63243"
  website: ""

galaxy_arms:
  - name: "Data Science & ML"
    color: "synapse_cyan"
    items:
      - "Python"
      - "Pandas"
      - "Machine Learning"
      - "Data Analysis"

  - name: "NLP & Knowledge"
    color: "dendrite_violet"
    items:
      - "NLP"
      - "Information Extraction"
      - "Knowledge Graphs"
      - "Text Mining"

  - name: "Backend & Cloud"
    color: "axon_amber"
    items:
      - "Node.js"
      - "APIs"
      - "Docker"
      - "AWS"

projects: []

theme:
  void: "#080c14"
  nebula: "#0f1623"
  star_dust: "#1a2332"
  synapse_cyan: "#00d4ff"
  dendrite_violet: "#a78bfa"
  axon_amber: "#ffb020"
  text_bright: "#f1f5f9"
  text_dim: "#94a3b8"
  text_faint: "#64748b"

stats:
  metrics:
    - "commits"
    - "stars"
    - "prs"
    - "issues"
    - "repos"

languages:
  exclude:
    - "HTML"
    - "CSS"
    - "Shell"
    - "Makefile"
  max_display: 8
"""

def run(cmd, check=True, capture=False, env=None, cwd=None):
    if capture:
        return subprocess.run(cmd, check=check, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env, cwd=cwd)
    return subprocess.run(cmd, check=check, env=env, cwd=cwd)

def git_root() -> Path:
    r = run(["git", "rev-parse", "--show-toplevel"], capture=True)
    return Path(r.stdout.strip())

def is_repo_structure(p: Path) -> bool:
    return (p / "generator").is_dir() and (p / "requirements.txt").is_file()

def find_imported_subdir(root: Path) -> Path | None:
    candidates = []
    for d in root.iterdir():
        if d.is_dir() and not d.name.startswith(".") and d.name.lower().endswith(("-main", "-master")):
            if is_repo_structure(d):
                candidates.append(d)
    if len(candidates) == 1:
        return candidates[0]
    for d in root.iterdir():
        if d.is_dir() and not d.name.startswith(".") and is_repo_structure(d):
            return d
    return None

def merge_move(src: Path, dst: Path):
    if src.is_dir():
        dst.mkdir(parents=True, exist_ok=True)
        for item in src.iterdir():
            merge_move(item, dst / item.name)
        try:
            src.rmdir()
        except OSError:
            pass
    else:
        if dst.exists():
            alt = dst.with_name(dst.name + ".from_import")
            shutil.move(str(src), str(alt))
        else:
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(src), str(dst))

def ensure_config(root: Path, username: str):
    config = root / "config.yml"
    if not config.exists():
        example = None
        for name in ["config.example.yml", "config.example.yaml", "config_example.yml", "config_example.yaml"]:
            p = root / name
            if p.exists():
                example = p
                break
        if not example:
            raise FileNotFoundError("Não achei config.example.yml na raiz.")
        shutil.copyfile(str(example), str(config))

    # Ajusta username no config.yml existente (sem destruir o resto)
    text = config.read_text(encoding="utf-8")
    if re.search(r"(?m)^\s*username\s*:", text):
        text = re.sub(r"(?m)^\s*username\s*:\s*.*$", f"username: {username}", text)
    else:
        text = f"username: {username}\n" + text
    config.write_text(text, encoding="utf-8")

    # Se config.yml estiver no .gitignore, adiciona exceção
    gitignore = root / ".gitignore"
    if gitignore.exists():
        gi = gitignore.read_text(encoding="utf-8")
        if re.search(r"(?m)^\s*config\.yml\s*$", gi) and "!config.yml" not in gi:
            gi = gi.rstrip() + "\n\n# allow profile config\n!config.yml\n"
            gitignore.write_text(gi, encoding="utf-8")

def write_config_force(root: Path, username: str):
    (root / "config.yml").write_text(luerfel_config_yml(username), encoding="utf-8")

def ensure_workflow(root: Path):
    wf = root / WORKFLOW_PATH
    wf.parent.mkdir(parents=True, exist_ok=True)

    if not wf.exists():
        wf.write_text(DEFAULT_WORKFLOW_YML, encoding="utf-8")
        return

    content = wf.read_text(encoding="utf-8")
    new = content

    # remove demo
    new = new.replace("python -m generator.main --demo", "python -m generator.main")

    # ensure permissions
    if re.search(r"(?m)^\s*permissions\s*:", new) is None:
        m = re.search(r"(?m)^\s*name\s*:\s*.*$", new)
        if m:
            insert_at = m.end()
            new = new[:insert_at] + "\n\npermissions:\n  contents: write\n" + new[insert_at:]
        else:
            new = "permissions:\n  contents: write\n\n" + new

    if new != content:
        wf.write_text(new, encoding="utf-8")

def venv_python(root: Path) -> Path:
    # linux/mac
    py = root / ".venv" / "bin" / "python"
    # windows fallback
    if not py.exists():
        py = root / ".venv" / "Scripts" / "python.exe"
    return py

def ensure_venv_and_install(root: Path):
    py = venv_python(root)
    if not py.exists():
        run([sys.executable, "-m", "venv", str(root / ".venv")])

    py = venv_python(root)
    if not py.exists():
        raise RuntimeError("Falha ao criar/achar .venv python.")

    run([str(py), "-m", "pip", "install", "--upgrade", "pip"])
    run([str(py), "-m", "pip", "install", "-r", str(root / "requirements.txt")])

def run_generator(root: Path):
    py = venv_python(root)
    env = os.environ.copy()
    # usa GITHUB_TOKEN se estiver setado no terminal
    run([str(py), "-m", "generator.main"], cwd=str(root), env=env)

def verify_outputs(root: Path):
    header = root / "assets" / "generated" / "galaxy-header.svg"
    if not header.exists():
        print("Aviso: assets/generated/galaxy-header.svg não foi encontrado.")
        return
    txt = header.read_text(encoding="utf-8", errors="ignore")
    if "Luerfel" not in txt:
        print("Aviso: galaxy-header.svg não contém 'Luerfel'.")
        print("  - Confirme se config.yml foi atualizado e se o generator está lendo o config certo.")
    else:
        print("OK: galaxy-header.svg contém 'Luerfel'.")

def git_commit_push(root: Path, do_commit: bool, do_push: bool, message: str):
    os.chdir(root)
    st = run(["git", "status", "--porcelain"], capture=True).stdout.strip()
    if not st:
        print("Nada para commitar.")
        return
    run(["git", "add", "-A"])
    if do_commit:
        run(["git", "commit", "-m", message])
        print("Commit criado.")
    if do_push:
        run(["git", "push"])
        print("Push feito.")

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--username", required=True, help="Seu username do GitHub (ex: luerfel)")
    ap.add_argument("--luerfel-config", action="store_true", help="Sobrescreve config.yml com um template pronto (inglês)")
    ap.add_argument("--fix-workflow", action="store_true", help="Cria/corrige .github/workflows/generate-profile.yml")
    ap.add_argument("--run", action="store_true", help="Cria venv, instala deps e roda o generator localmente")
    ap.add_argument("--commit", action="store_true", help="Faz git commit automaticamente")
    ap.add_argument("--push", action="store_true", help="Faz git push automaticamente (requer auth)")
    ap.add_argument("--message", default="chore: update galaxy profile", help="Mensagem do commit")
    args = ap.parse_args()

    root = git_root()
    print(f"Repo root: {root}")

    # Move de subpasta *-main se necessário
    if not is_repo_structure(root):
        sub = find_imported_subdir(root)
        if sub:
            print(f"Encontrado projeto em subpasta: {sub.name} — movendo para a raiz…")
            for item in list(sub.iterdir()):
                merge_move(item, root / item.name)
            try:
                sub.rmdir()
            except OSError:
                pass
        else:
            raise RuntimeError("Não encontrei generator/ e requirements.txt na raiz nem em subpasta *-main.")
    else:
        print("Estrutura OK na raiz.")

    # config.yml
    ensure_config(root, args.username)
    if args.luerfel_config:
        write_config_force(root, args.username)
        print("config.yml sobrescrito com template Luerfel (inglês).")
    else:
        print("config.yml OK (username ajustado).")

    # workflow
    if args.fix_workflow:
        ensure_workflow(root)
        print("Workflow OK (.github/workflows/generate-profile.yml).")

    # run generator local
    if args.run:
        ensure_venv_and_install(root)
        print("Deps instaladas na .venv.")
        run_generator(root)
        print("SVGs gerados.")
        verify_outputs(root)

    # git ops
    if args.commit or args.push:
        git_commit_push(root, do_commit=args.commit, do_push=args.push, message=args.message)
    else:
        print("Pronto. Se quiser salvar no repo: git add -A && git commit -m '...' && git push")

if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"ERRO: {e}", file=sys.stderr)
        sys.exit(1)