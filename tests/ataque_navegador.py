"""Teste de ataque no navegador (XSS / injeção de HTML) contra o site gerado.

Abre o HTML num Edge/Chrome headless, injeta um script de auditoria SÓ na cópia de teste e
exercita o site como um usuário faria: troca de aba, ordenação, cliques em linhas, filtros,
busca (com payload) e tooltips de todos os elementos. Depois procura:
  * execução de código (window.__pwn, document.title == "PWNED");
  * elementos que não deveriam existir (<img src=x>, <svg onload>, <script> extra, handlers on*);
  * tooltip com HTML além do <b> do título.
Uso: auditar(caminho_html, sem_csp=False) -> dict com os achados.
"""
import base64
import hashlib
import json
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

NAVEGADORES = [
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    "/usr/bin/google-chrome", "/usr/bin/chromium", "/usr/bin/chromium-browser",
]

SCRIPT_AUDITORIA = r"""
<script id="auditoria">
(async function(){
  const R={pwn:false,titulo:document.title,achados:[],passos:0};
  const sleep=ms=>new Promise(r=>setTimeout(r,ms));
  const PAY=%PAYLOAD%;
  const scriptsOriginais=document.querySelectorAll('script').length;   // principal + esta auditoria
  function varrer(onde){
    R.passos++;
    if(window.__pwn) {R.pwn=true; R.achados.push({onde,tipo:'execucao: window.__pwn'});}
    if(document.title==='PWNED'){R.pwn=true; R.achados.push({onde,tipo:'execucao: title alterado'});}
    document.querySelectorAll('img[src="x"],svg[onload],[onerror],[onload],[onclick]:not(button)').forEach(e=>{
      R.achados.push({onde,tipo:'elemento injetado',tag:e.tagName,html:e.outerHTML.slice(0,160)});});
    if(document.querySelectorAll('script').length!==scriptsOriginais) R.achados.push({onde,tipo:'script extra no DOM'});
    const tt=document.getElementById('tt');
    if(tt&&[...tt.children].some(c=>c.tagName!=='B')) R.achados.push({onde,tipo:'tooltip com HTML',html:tt.innerHTML.slice(0,160)});
  }
  const abas=[...document.querySelectorAll('.tab')].filter(t=>t.style.display!=='none').map(t=>t.dataset.p);
  for(const p of abas){
    document.querySelector('.tab[data-p="'+p+'"]').click(); await sleep(30); varrer(p+':abrir');
    const n=document.querySelectorAll('.page.on th[data-sort]').length;
    for(let i=0;i<n;i++){ const th=document.querySelectorAll('.page.on th[data-sort]')[i]; if(th){th.click(); await sleep(5);} }
    varrer(p+':ordenar');
    for(const sel of ['tr[data-mae]','tr[data-sim]']){
      const linhas=document.querySelectorAll('.page.on '+sel); for(let i=0;i<Math.min(linhas.length,6);i++){ document.querySelectorAll('.page.on '+sel)[i]?.click(); await sleep(5);} }
    varrer(p+':clicar-linha');
    for(const s of document.querySelectorAll('.page.on select, .filters select')){
      for(const o of [...s.options].slice(0,8)){ s.value=o.value; s.dispatchEvent(new Event('change',{bubbles:true})); await sleep(3);} }
    varrer(p+':filtros');
    for(const i of document.querySelectorAll('.page.on input[type=search]')){
      i.value=PAY; i.dispatchEvent(new Event('input',{bubbles:true})); await sleep(5); i.value=''; i.dispatchEvent(new Event('input',{bubbles:true})); }
    varrer(p+':busca');
    const alvos=[...document.querySelectorAll('.page.on [data-tip]')]; const passo=Math.max(1,Math.floor(alvos.length/120));
    for(let i=0;i<alvos.length;i+=passo){
      alvos[i].dispatchEvent(new PointerEvent('pointermove',{bubbles:true,clientX:20,clientY:20}));
      if(i%(passo*10)===0) varrer(p+':tooltip#'+i); }
    varrer(p+':tooltips');
  }
  R.titulo=document.title; R.paginaTitulo=R.titulo;
  const pre=document.createElement('pre'); pre.id='audit-result'; pre.textContent=JSON.stringify(R); document.body.appendChild(pre);
})();
</script>
"""


def achar_navegador():
    for c in NAVEGADORES:
        if Path(c).exists():
            return c
    return shutil.which("msedge") or shutil.which("chrome") or shutil.which("chromium")


def auditar(html: Path, payload_busca: str, sem_csp: bool = False, orcamento_ms: int = 40000) -> dict:
    nav = achar_navegador()
    if not nav:
        raise RuntimeError("Edge/Chrome não encontrado")
    txt = Path(html).read_text(encoding="utf-8")
    if sem_csp:  # só no teste: tira a CSP para medir se o ESCAPE sozinho segura o ataque
        txt = re.sub(r'<meta http-equiv="Content-Security-Policy"[^>]*>', "", txt)
    # o payload tem </script>: precisa ser escapado também aqui, senão fecha o script de auditoria
    payload_js = json.dumps(payload_busca).replace("<", "\\u003c").replace(">", "\\u003e")
    audit = SCRIPT_AUDITORIA.replace("%PAYLOAD%", payload_js)
    txt = txt.replace("</body>", audit + "</body>")
    if not sem_csp:
        # a CSP real bloquearia o script de auditoria (injetado só neste teste): libera o hash EXATO dele
        corpo = re.search(r"<script id=\"auditoria\">(.*?)</script>", txt, re.S).group(1)
        h = "sha256-" + base64.b64encode(hashlib.sha256(corpo.encode("utf-8")).digest()).decode("ascii")
        txt = txt.replace("script-src '", f"script-src '{h}' '", 1)
    with tempfile.TemporaryDirectory() as tmp:
        alvo = Path(tmp) / "audit.html"
        alvo.write_text(txt, encoding="utf-8")
        perfil = Path(tmp) / "perfil"
        r = subprocess.run([nav, "--headless=new", "--disable-gpu", "--no-first-run", f"--user-data-dir={perfil}",
                            f"--virtual-time-budget={orcamento_ms}", "--dump-dom", alvo.as_uri()],
                           capture_output=True, timeout=240)
    dom = r.stdout.decode("utf-8", "replace")
    m = re.search(r'<pre id="audit-result">(.*?)</pre>', dom, re.S)
    if not m:
        erro = re.search(r'<div id="alerta">(.*?)</div>\s*</div>', dom, re.S)
        return {"erro": "auditoria não terminou", "dom_tamanho": len(dom),
                "alerta": (erro.group(1)[:400] if erro else ""), "stderr": r.stderr.decode("utf-8", "replace")[-300:],
                "titulo": (re.search(r"<title>(.*?)</title>", dom, re.S) or [None, ""])[1][:80]}
    import html as _h
    res = json.loads(_h.unescape(m.group(1)))
    # confere também o DOM final serializado
    res["dom_img_x"] = len(re.findall(r'<img[^>]+src="x"', dom))
    res["dom_svg_onload"] = len(re.findall(r"<svg[^>]+onload", dom))
    return res
