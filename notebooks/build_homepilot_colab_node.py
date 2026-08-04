"""Generator for notebooks/homepilot_colab_node.ipynb (PR 4).

The notebook is a *preset*: thin cells that delegate every decision to
``ollabridge.node.colab`` (unit-tested) and pair/connect via the existing
``ollabridge-node`` CLI. Keeping the notebook generated-from-source means the
cells stay in lock-step with the helper and are trivial to review as plain text.

Run:  python notebooks/build_homepilot_colab_node.py
"""

from __future__ import annotations

import json
from pathlib import Path


def md(*lines: str) -> dict:
    return {"cell_type": "markdown", "metadata": {}, "source": _src(lines)}


def code(*lines: str) -> dict:
    return {"cell_type": "code", "metadata": {}, "execution_count": None, "outputs": [], "source": _src(lines)}


def _src(lines):
    text = "\n".join(lines)
    out = text.splitlines(keepends=True)
    return out


CELLS = [
    md(
        "# HomePilot × OllaBridge — Colab GPU node (preset)",
        "",
        "Turn this free Colab runtime into a **GPU worker** that HomePilot can",
        "route models to, through OllaBridge Cloud. No public tunnel, no static",
        "IP: the node connects **outbound** over WSS.",
        "",
        "Sequence (each step is one cell):",
        "1. Confirm a GPU runtime",
        "2. Install OllaBridge + the selected runtime",
        "3. Choose runtime (chat / image / video) & models — **before** downloading",
        "4. Reuse a saved node identity (optional: Google Drive)",
        "5. Start the runtime (Ollama or ComfyUI)",
        "6. Pull the selected models",
        "7. Pair (device code) & review the capability manifest",
        "8. Connect + heartbeat — leave running; **Stop** terminates cleanly",
        "",
        "> Free experimental compute. Sessions are temporary and may disconnect —",
        "> not for always-on production.",
    ),
    code(
        "#@title 0 · Config (edit these)",
        "CLOUD_URL   = 'https://app.ollabridge.com'  #@param {type:'string'}",
        "RUNTIME     = 'chat'  #@param ['chat', 'image', 'video']",
        "# Comma-separated. Chat: Ollama model ids. Image/video: workflow model ids.",
        "MODELS      = 'llama3.2:3b, qwen2.5:0.5b'  #@param {type:'string'}",
        "# Optional: reuse the same device across runtimes by stashing identity here.",
        "DRIVE_DIR   = ''  #@param {type:'string'}",
        "REQUESTED   = [m.strip() for m in MODELS.split(',') if m.strip()]",
    ),
    md("## 1 · Confirm a GPU runtime"),
    code(
        "import subprocess",
        "gpu = subprocess.run(['nvidia-smi'], capture_output=True, text=True)",
        "assert gpu.returncode == 0, 'No GPU. Runtime → Change runtime type → GPU, then re-run.'",
        "print(gpu.stdout.split(chr(10))[0])",
    ),
    md("## 2 · Install OllaBridge + the selected runtime"),
    code(
        "!python -m pip -q install -U ollabridge",
        "from ollabridge.node import colab",
        "plan = colab.plan_runtime(RUNTIME)",
        "colab.apply_runtime_env(plan)",
        "if plan.uses_ollama:",
        "    get_ipython().system('curl -fsSL https://ollama.com/install.sh | sh')",
        "else:",
        "    print('Image/video runtime — install ComfyUI at OLLABRIDGE_COMFYUI_URL (see docs).')",
        "print('Runtime plan:', plan)",
    ),
    md(
        "## 3 · Choose models — validated **before** any download",
        "",
        "Generation models are checked against the workflow catalog, so a typo",
        "fails here instead of after a multi-GB pull.",
    ),
    code(
        "sel = colab.select_models(RUNTIME, REQUESTED)",
        "print('Will download:', sel.chat_models or sel.gen_models)",
        "if sel.unknown:",
        "    print('Unknown for this runtime (skipped):', sel.unknown)",
        "assert sel.ok or (sel.chat_models or sel.gen_models), 'Nothing valid to run — fix MODELS.'",
    ),
    md(
        "## 4 · Reuse a saved node identity (optional)",
        "",
        "Colab storage is ephemeral. Point `DRIVE_DIR` at a mounted Google Drive",
        "folder to reuse the *same* Cloud device instead of re-pairing each session.",
    ),
    code(
        "if DRIVE_DIR:",
        "    restored = colab.restore_identity(DRIVE_DIR)",
        "    print('Restored identity from Drive.' if restored else 'No stashed identity yet.')",
        "print('Identity:', colab.identity_status())",
    ),
    md("## 5 · Start the runtime (background)"),
    code(
        "import subprocess, time",
        "procs = []",
        "if plan.uses_ollama:",
        "    ollama = subprocess.Popen(['ollama', 'serve'],",
        "                              stdout=open('/tmp/ollama.log', 'w'),",
        "                              stderr=subprocess.STDOUT)",
        "    procs.append(ollama)",
        "    time.sleep(5)",
        "    print('Ollama started →', colab.tail_log('/tmp/ollama.log', 3) or '(starting)')",
        "else:",
        "    print('Ensure ComfyUI is running at', plan.env.get('OLLABRIDGE_COMFYUI_URL', 'http://127.0.0.1:8188'))",
    ),
    md("## 6 · Pull the selected models"),
    code(
        "if RUNTIME == 'chat':",
        "    for m in sel.chat_models:",
        "        print('Pulling', m); import subprocess; subprocess.run(['ollama', 'pull', m], check=False)",
        "else:",
        "    print('Generation models are served from present workflows:', sel.gen_models)",
    ),
    md(
        "## 7 · Pair (device code) & review the capability manifest",
        "",
        "Skip pairing if step 4 restored an identity. The manifest shows exactly",
        "what this node will advertise to the Cloud.",
    ),
    code(
        "import json",
        "manifest = colab.capability_manifest(RUNTIME, chat_models=sel.chat_models)",
        "print(json.dumps(manifest, indent=2))",
        "",
        "if not colab.identity_status()['paired']:",
        "    cmd = colab.pair_command(CLOUD_URL)",
        "    print('Pairing — open the printed URL and enter the code:')",
        "    print(' '.join(cmd))",
        "    get_ipython().system(' '.join(cmd))",
        "    if DRIVE_DIR:",
        "        colab.stash_identity(DRIVE_DIR); print('Identity stashed to Drive for reuse.')",
        "else:",
        "    print('Already paired — reusing device', colab.identity_status()['device_id'])",
    ),
    md(
        "## 8 · Connect + heartbeat",
        "",
        "This starts the outbound relay and keeps the node online. Leave it",
        "running. Use the **Heartbeat** cell to check state; **Stop** to terminate",
        "cleanly.",
    ),
    code(
        "import subprocess",
        "connect_cmd = colab.connect_command(CLOUD_URL)",
        "connect = subprocess.Popen(connect_cmd,",
        "                           stdout=open('/tmp/connect.log', 'w'),",
        "                           stderr=subprocess.STDOUT)",
        "procs.append(connect)",
        "print('Connecting:', ' '.join(connect_cmd))",
    ),
    code(
        "#@title Heartbeat (re-run any time)",
        "log = colab.tail_log('/tmp/connect.log', 20)",
        "print('State:', colab.connection_state(log))",
        "print(log)",
    ),
    code(
        "#@title Stop — terminate cleanly",
        "colab.terminate(procs)",
        "print('Stopped', len(procs), 'process(es). This node is now offline.')",
    ),
]


def main() -> None:
    nb = {
        "cells": CELLS,
        "metadata": {
            "kernelspec": {"display_name": "Python 3", "language": "python", "name": "python3"},
            "language_info": {"name": "python"},
            "colab": {"provenance": []},
            "accelerator": "GPU",
        },
        "nbformat": 4,
        "nbformat_minor": 5,
    }
    out = Path(__file__).parent / "homepilot_colab_node.ipynb"
    out.write_text(json.dumps(nb, indent=1) + "\n", encoding="utf-8")
    print("wrote", out)


if __name__ == "__main__":
    main()
