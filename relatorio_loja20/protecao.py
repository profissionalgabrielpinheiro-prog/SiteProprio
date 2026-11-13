"""Protege o site publicado com usuário e senha, de verdade: o conteúdo é CIFRADO.

Uma tela de login em JavaScript sobre o HTML original não protegeria nada (os dados de vendas
estariam no código-fonte). Aqui o site inteiro é cifrado com AES-256-GCM; a chave é derivada de
usuário + senha com PBKDF2-SHA256 (600 mil iterações). O arquivo publicado só contém texto cifrado
e a tela de login: sem a senha certa o navegador não consegue decifrar, nem lendo o código-fonte.

Limites honestos: quem baixar o arquivo pode tentar adivinhar a senha offline. Por isso use uma
senha longa e não a reaproveite. A senha NUNCA fica no código nem no Git (variáveis de ambiente).
"""
import base64
import hashlib
import os
from pathlib import Path

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

ITERACOES = 600_000
_AAD = b"loja20-relatorio-v1"

_LOGIN = """<!doctype html>
<html lang="pt-BR">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta http-equiv="Content-Security-Policy" content="__CSP__">
<meta name="referrer" content="no-referrer">
<meta name="robots" content="noindex, nofollow, noarchive">
<title>Acesso restrito</title>
<style>
:root{color-scheme:light dark}
body{margin:0;min-height:100vh;display:grid;place-items:center;font-family:system-ui,Segoe UI,sans-serif;background:#f4f4f1;color:#0b0b0b}
@media (prefers-color-scheme:dark){body{background:#0d0d0d;color:#f0efec}input{background:#232321;color:#f0efec;border-color:#444}}
form{width:min(340px,86vw);display:grid;gap:12px;padding:28px;border-radius:12px;border:1px solid rgba(128,128,128,.3)}
h1{font-size:1.1rem;margin:0 0 4px}
input,button{font:inherit;padding:10px 12px;border-radius:8px;border:1px solid #bbb}
button{background:#2a78d6;color:#fff;border-color:#2a78d6;cursor:pointer}
button:disabled{opacity:.6;cursor:wait}
#msg{min-height:1.2em;font-size:.85rem;color:#c42f2f}
</style>
</head>
<body>
<form id="f" autocomplete="on">
<h1>Acesso restrito</h1>
<input id="u" name="username" placeholder="Usuário" autocomplete="username" required autofocus>
<input id="s" name="password" type="password" placeholder="Senha" autocomplete="current-password" required>
<button id="b" type="submit">Entrar</button>
<div id="msg" role="alert"></div>
</form>
<div id="d" hidden data-s="__SAL__" data-i="__IV__" data-n="__ITER__" data-c="__CIFRA__"></div>
<script>
(function(){
"use strict";
if(window.top!==window.self){document.documentElement.replaceChildren();return;}
const d=document.getElementById("d").dataset, msg=document.getElementById("msg");
const b64=s=>Uint8Array.from(atob(s),c=>c.charCodeAt(0));
document.getElementById("f").addEventListener("submit",async e=>{
  e.preventDefault();
  const btn=document.getElementById("b"); btn.disabled=true; msg.textContent="";
  try{
    const u=document.getElementById("u").value.trim().toLowerCase(), s=document.getElementById("s").value;
    const enc=new TextEncoder();
    const base=await crypto.subtle.importKey("raw",enc.encode(u+String.fromCharCode(0)+s),"PBKDF2",false,["deriveKey"]);
    const key=await crypto.subtle.deriveKey({name:"PBKDF2",salt:b64(d.s),iterations:+d.n,hash:"SHA-256"},
      base,{name:"AES-GCM",length:256},false,["decrypt"]);
    const claro=await crypto.subtle.decrypt({name:"AES-GCM",iv:b64(d.i),additionalData:enc.encode("__AAD__")},key,b64(d.c));
    const html=new TextDecoder().decode(claro);
    document.open(); document.write(html); document.close();
  }catch(_){
    msg.textContent="Usu"+String.fromCharCode(225)+"rio ou senha incorretos."; btn.disabled=false;
  }
});
})();
</script>
</body>
</html>
"""


def _sha(texto: str) -> str:
    return "sha256-" + base64.b64encode(hashlib.sha256(texto.encode("utf-8")).digest()).decode("ascii")


def _csp(html_original: str, login_sem_csp: str) -> str:
    import re
    unico = lambda rx, s: re.findall(rx, s, re.S)  # noqa: E731
    sc_l = unico(r"<script[^>]*>(.*?)</script>", login_sem_csp)
    st_l = unico(r"<style[^>]*>(.*?)</style>", login_sem_csp)
    # ignora scripts externos e o bloco de dados JSON (que não executa)
    sc_o = unico(r"<script(?![^>]*\bsrc=)(?![^>]*application/json)[^>]*>(.*?)</script>", html_original)
    st_o = unico(r"<style[^>]*>(.*?)</style>", html_original)
    if len(sc_l) != 1 or len(st_l) != 1 or len(sc_o) != 1 or len(st_o) != 1:
        raise ValueError("Esperava 1 <script> e 1 <style> inline no login e no site.")
    # os hashes do site original também entram: depois de decifrar, o site é escrito nesta página
    return "; ".join([
        "default-src 'none'",
        f"script-src '{_sha(sc_l[0])}' '{_sha(sc_o[0])}'",
        f"style-src-elem '{_sha(st_l[0])}' '{_sha(st_o[0])}'",
        "style-src-attr 'unsafe-inline'",
        "img-src data:", "connect-src 'none'", "font-src 'none'", "frame-src 'none'", "worker-src 'none'",
        "media-src 'none'", "manifest-src 'none'", "object-src 'none'", "base-uri 'none'", "form-action 'none'",
    ])


def proteger(html: str, usuario: str, senha: str) -> str:
    """Devolve a página de login com `html` cifrado dentro."""
    if len(senha) < 8 or not usuario.strip():
        raise ValueError("Usuário vazio ou senha com menos de 8 caracteres.")
    sal, iv = os.urandom(16), os.urandom(12)
    chave = hashlib.pbkdf2_hmac("sha256", (usuario.strip().lower() + "\0" + senha).encode("utf-8"), sal, ITERACOES, 32)
    cifra = AESGCM(chave).encrypt(iv, html.encode("utf-8"), _AAD)
    b = lambda x: base64.b64encode(x).decode("ascii")  # noqa: E731
    login = (_LOGIN.replace("__AAD__", _AAD.decode()).replace("__SAL__", b(sal)).replace("__IV__", b(iv))
             .replace("__ITER__", str(ITERACOES)).replace("__CIFRA__", b(cifra)))
    return login.replace("__CSP__", _csp(html, login.replace("__CSP__", "")), 1)


def publicar(html_path: Path, destino: Path, usuario: str, senha: str) -> Path:
    """Lê o site gerado, cifra e grava `destino/index.html` (+ _headers do Cloudflare Pages)."""
    destino.mkdir(parents=True, exist_ok=True)
    saida = destino / "index.html"
    saida.write_text(proteger(Path(html_path).read_text(encoding="utf-8"), usuario, senha), encoding="utf-8")
    (destino / "_headers").write_text(
        "/*\n  X-Frame-Options: DENY\n  X-Content-Type-Options: nosniff\n  Referrer-Policy: no-referrer\n"
        "  X-Robots-Tag: noindex, nofollow\n  Cache-Control: no-store\n", encoding="utf-8")
    return saida
