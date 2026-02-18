#!/usr/bin/env python3
"""
Bootstrap para repos de perfil estilo "galaxy-profile".

O que faz:
- Detecta subpasta importada via zip (ex: luerfel-galaxy-main/) e move o conteúdo para a raiz
- Garante config.yml (copiando de config.example.yml) e seta username
- Se config.yml estiver no .gitignore, adiciona exceção (!config.yml)
- Atualiza workflow: remove --demo e adiciona permissions: contents: write
- (Opcional) substitui README.md pelo README.profile.md (com backup)
- (Opcional) git add/commit e git push

Uso:
  python3 bootstrap_galaxy_profile.py --username luerfel --replace-readme --commit --push
"""

import argparse
import datetime as dt
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

def run(cmd, check=True, capture=False):
    if capture:
        return subprocess.run(cmd, check=check, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    return subprocess.run(cmd, check=check)

def git_root() -> Path:
    r = run(["git", "rev-parse", "--show-toplevel"], capture=True)
    return Path(r.stdout.strip())

def is_repo_structure(p: Path) -> bool:
    # Heurística mínima: presença de generator/ e requirements.txt
    return (p / "generator").is_dir() and (p / "requirements.txt").is_file()

def find_imported_subdir(root: Path) -> Path | None:
    # Caso típico do zip: uma pasta "*-main" com o projeto dentro
    candidates = []
    for d in root.iterdir():
        if d.is_dir() and not d.name.startswith(".") and d.name.lower().endswith(("-main", "-master")):
            if is_repo_structure(d):
                candidates.append(d)
    if len(candidates) == 1:
        return candidates[0]
    # fallback: achar qualquer subdir que tenha generator/ e requirements.txt
    for d in root.iterdir():
        if d.is_dir() and not d.name.startswith(".") and is_repo_structure(d):
            return d
    return None

def safe_backup(path: Path) -> Path:
    ts = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    backup = path.with_name(f"{path.name}.backup.{ts}")
    shutil.move(str(path), str(backup))
    return backup

def merge_move(src: Path, dst: Path):
    """
    Move src -> dst, mesclando diretórios.
    Se arquivo conflitar, mantém o dst e salva o src como *.from_import
    """
    if src.is_dir():
        dst.mkdir(parents=True, exist_ok=True)
        for item in src.iterdir():
            merge_move(item, dst / item.name)
        # tenta remover se vazio
        try:
            src.rmdir()
        except OSError:
            pass
    else:
        if dst.exists():
            # não sobrescreve; salva a versão importada com sufixo
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

    # Atualiza username: luerfel (apenas substituição simples no topo)
    text = config.read_text(encoding="utf-8")
    if re.search(r"(?m)^\s*username\s*:", text):
        text = re.sub(r"(?m)^\s*username\s*:\s*.*$", f"username: {username}", text)
    else:
        text = f"username: {username}\n" + text
    config.write_text(text, encoding="utf-8")

    # Se config.yml estiver ignorado, adiciona exceção no .gitignore
    gitignore = root / ".gitignore"
    if gitignore.exists():
        gi = gitignore.read_text(encoding="utf-8")
        # se houver regra que ignore config.yml, adiciona exceção no fim
        if re.search(r"(?m)^\s*config\.yml\s*$", gi) and "!config.yml" not in gi:
            gi = gi.rstrip() + "\n\n# allow profile config\n!config.yml\n"
            gitignore.write_text(gi, encoding="utf-8")

def update_workflow(root: Path):
    wf_dir = root / ".github" / "workflows"
    if not wf_dir.exists():
        raise FileNotFoundError("Não achei .github/workflows. O zip pode não ter extraído corretamente.")

    # Atualiza qualquer workflow que rode generator.main
    changed_any = False
    for wf in wf_dir.glob("*.yml"):
        content = wf.read_text(encoding="utf-8")

        if "python -m generator.main" not in content:
            continue

        new = content

        # Remove --demo
        new = new.replace("python -m generator.main --demo", "python -m generator.main")

        # Garante permissions: contents: write no topo (nível do workflow)
        if re.search(r"(?m)^\s*permissions\s*:", new) is None:
            # tenta inserir logo após "name:"
            m = re.search(r"(?m)^\s*name\s*:\s*.*$", new)
            if m:
                insert_at = m.end()
                new = new[:insert_at] + "\n\npermissions:\n  contents: write\n" + new[insert_at:]
            else:
                # topo do arquivo
                new = "permissions:\n  contents: write\n\n" + new

        if new != content:
            wf.write_text(new, encoding="utf-8")
            changed_any = True

    if not changed_any:
        print("Aviso: não achei workflow com 'python -m generator.main' para ajustar (ou já estava ajustado).")

def replace_readme(root: Path):
    profile = root / "README.profile.md"
    if not profile.exists():
        raise FileNotFoundError("Não achei README.profile.md na raiz.")
    readme = root / "README.md"
    if readme.exists():
        b = safe_backup(readme)
        print(f"Backup do README.md criado em: {b.name}")
    shutil.copyfile(str(profile), str(readme))

def git_commit_push(root: Path, do_commit: bool, do_push: bool, message: str):
    os.chdir(root)
    # status
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
    ap.add_argument("--replace-readme", action="store_true", help="Substitui README.md por README.profile.md (com backup)")
    ap.add_argument("--commit", action="store_true", help="Faz git commit automaticamente")
    ap.add_argument("--push", action="store_true", help="Faz git push automaticamente (requer autenticação configurada)")
    ap.add_argument("--message", default="chore: bootstrap galaxy profile", help="Mensagem do commit")
    args = ap.parse_args()

    root = git_root()
    print(f"Repo root: {root}")

    # Se estrutura está dentro de subpasta, move pra raiz
    if not is_repo_structure(root):
        sub = find_imported_subdir(root)
        if not sub:
            raise RuntimeError("Não encontrei a subpasta importada com generator/ e requirements.txt.")
        print(f"Encontrado projeto em subpasta: {sub.name} — movendo para a raiz…")
        for item in list(sub.iterdir()):
            # move/mescla para a raiz
            merge_move(item, root / item.name)
        # tenta remover subpasta vazia
        try:
            sub.rmdir()
        except OSError:
            pass
    else:
        print("Estrutura já está na raiz. (Nada a mover)")

    # Config
    ensure_config(root, args.username)
    print("config.yml OK (username ajustado).")

    # Workflow
    update_workflow(root)
    print("Workflow ajustado (sem --demo e com permissions).")

    # README
    if args.replace_readme:
        replace_readme(root)
        print("README.md substituído pelo README.profile.md.")

    # Git ops
    if args.commit or args.push:
        git_commit_push(root, do_commit=args.commit, do_push=args.push, message=args.message)
    else:
        print("Pronto. Agora rode manualmente: git add -A && git commit -m '...' && git push")

if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"ERRO: {e}", file=sys.stderr)
        sys.exit(1)