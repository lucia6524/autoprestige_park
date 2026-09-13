"""Audit console du site (usage local uniquement) : charge chaque page du
build avec Chrome headless et collecte erreurs JS, console.error/warn,
rejections, ressources 404 et violations CSP.

Usage : python frontend/scripts/__audit_pages.py [--chrome PATH] [--port N]
Le serveur est démarré/arrêté par le script ; aucune trace laissée dans dist/.
"""
import argparse
import atexit
import http.server
import json
import os
import re
import functools
import subprocess
import sys
import threading
import time
import socketserver
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent          # frontend/
DIST = ROOT / "dist"
DUMPS = ROOT / ".audit-dumps"
PROBE_SRC = Path(__file__).resolve().parent / "__audit_probe.js"
PROBE = DIST / "__audit.js"

CHROME_CANDIDATES = [
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    os.path.expandvars(r"%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe"),
]

INJECT = '<script src="__audit.js"></script>'


def find_chrome() -> str:
    for c in CHROME_CANDIDATES:
        if os.path.exists(c):
            return c
    print("Chrome introuvable", file=sys.stderr)
    sys.exit(1)


def inject_pages() -> list[str]:
    """Insère le probe en tête de <head> dans chaque HTML du build."""
    pages = []
    for html in sorted(DIST.glob("*.html")):
        text = html.read_text(encoding="utf-8")
        if "__audit.js" in text:
            pages.append(html.name)
            continue
        if "<head>" not in text:
            continue
        html.write_text(text.replace("<head>", "<head>" + INJECT, 1), encoding="utf-8")
        pages.append(html.name)
    return pages


def restore_pages(pages: list[str]) -> None:
    """Retire le probe (les fichiers dist/ redeviennent identiques au build)."""
    for name in pages:
        html = DIST / name
        try:
            text = html.read_text(encoding="utf-8")
        except OSError:
            continue
        html.write_text(text.replace(INJECT, "", 1), encoding="utf-8")
    if PROBE.exists():
        PROBE.unlink()


def make_handler():
    return functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(DIST))


def serve(port: int, stop: threading.Event):
    socketserver.ThreadingTCPServer.allow_reuse_address = True
    httpd = socketserver.ThreadingTCPServer(("127.0.0.1", port), make_handler())
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    stop.wait()
    httpd.shutdown()
    httpd.server_close()


def audit_page(chrome: str, port: int, page: str, tmpdir: Path) -> dict:
    url = f"http://127.0.0.1:{port}/{page}"
    cmd = [
        chrome,
        "--headless=new",
        "--disable-gpu",
        "--no-first-run",
        "--disable-extensions",
        "--virtual-time-budget=6000",
        f"--user-data-dir={tmpdir}",
        f"--dump-dom={url}",
    ]
    # --dump-dom n'accepte pas l'URL en valeur d'option : forme classique
    cmd = cmd[:-1] + ["--dump-dom", url]
    try:
        out = subprocess.run(cmd, capture_output=True, text=True, timeout=40, encoding="utf-8", errors="replace").stdout
    except subprocess.TimeoutExpired:
        return {"page": page, "timeout": True}

    (DUMPS / (page + ".html")).write_text(out, encoding="utf-8")
    m = re.search(r"AUDIT_JSON=(\{.*\})", out)
    if not m:
        return {"page": page, "probeMissing": True}
    try:
        data = json.loads(m.group(1))
    except json.JSONDecodeError:
        return {"page": page, "probeJsonBroken": True}
    data["page"] = page
    return data


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--chrome", default=find_chrome())
    ap.add_argument("--port", type=int, default=8910)
    args = ap.parse_args()
    if not PROBE_SRC.exists():
        print("probe manquant : scripts/__audit_probe.js", file=sys.stderr)
        sys.exit(1)
    DIST.mkdir(exist_ok=True)
    PROBE.write_text(PROBE_SRC.read_text(encoding="utf-8"), encoding="utf-8")

    DUMPS.mkdir(exist_ok=True)
    pages = inject_pages()
    print(f"[audit] {len(pages)} pages instrumentées")

    tmpdir = DUMPS / "chrome-profile"
    tmpdir.mkdir(exist_ok=True)

    stop = threading.Event()
    threading.Thread(target=serve, args=(args.port, stop), daemon=True).start()
    time.sleep(1.0)

    results = []
    try:
        for page in pages:
            r = audit_page(args.chrome, args.port, page, tmpdir)
            results.append(r)
            print(f"[audit] {page} -> "
                  f"js={len(r.get('jsErrors', []))} "
                  f"err={len(r.get('consoleErrors', []))} "
                  f"warn={len(r.get('consoleWarns', []))} "
                  f"res={len(r.get('resources', []))} "
                  f"csp={len(r.get('csp', []))} "
                  f"rej={len(r.get('rejections', []))}")
    finally:
        stop.set()
        time.sleep(0.3)
        restore_pages(pages)
        print("[audit] probe retiré de dist/")

    (DUMPS / "results.json").write_text(json.dumps(results, ensure_ascii=False, indent=1), encoding="utf-8")

    total = {k: 0 for k in ("jsErrors", "consoleErrors", "consoleWarns", "resources", "csp", "rejections")}
    dirty = []
    for r in results:
        if r.get("timeout") or r.get("probeMissing") or r.get("probeJsonBroken"):
            dirty.append(r)
            continue
        for k in total:
            total[k] += len(r.get(k, []))
        if any(r.get(k) for k in total):
            dirty.append(r)

    print("\n===== RAPPORT =====")
    print(f"pages: {len(results)} | jsErrors={total['jsErrors']} consoleErrors={total['consoleErrors']} "
          f"consoleWarns={total['consoleWarns']} ressourcesKO={total['resources']} csp={total['csp']} rejections={total['rejections']}")
    for r in dirty:
        print("\n--", r["page"])
        if r.get("timeout"):
            print("   TIMEOUT (page non chargée dans le délai)")
            continue
        if r.get("probeMissing"):
            print("   PROBE ABSENT (dump trop tôt ?)")
            continue
        if r.get("probeJsonBroken"):
            print("   JSON probe illisible")
            continue
        for k in total:
            for item in r.get(k, []):
                print(f"   [{k}] {item}")


if __name__ == "__main__":
    main()
