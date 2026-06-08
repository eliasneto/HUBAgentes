import os, json, time, sys
from pathlib import Path
from dotenv import load_dotenv
load_dotenv()

sys.stdout.reconfigure(encoding="utf-8")

import google.genai as genai
import google.genai.types as types

DOCS        = Path("docs_gerados")
IMGS        = DOCS / "imagens"
IMGS_GEMINI = DOCS / "imagens_gemini"
CACHE_FILE  = DOCS / "descricoes_cache.json"

client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))
rotas  = json.loads((DOCS / "rotas.json").read_text(encoding="utf-8"))
shots  = json.loads((DOCS / "screenshots.json").read_text(encoding="utf-8")) if (DOCS / "screenshots.json").exists() else {}
cache  = json.loads(CACHE_FILE.read_text(encoding="utf-8")) if CACHE_FILE.exists() else {}

nome = Path(".").resolve().name.replace("-", " ").replace("_", " ").title()
data = time.strftime("%d/%m/%Y")


def salvar_cache():
    CACHE_FILE.write_text(json.dumps(cache, indent=2, ensure_ascii=False), encoding="utf-8")


def gemini_png_para(display_nome):
    stem = Path(display_nome).stem
    candidato = IMGS_GEMINI / f"{stem}.png"
    if candidato.exists():
        return candidato
    fallback = IMGS / display_nome
    return fallback if fallback.exists() and display_nome.endswith(".png") else None


def descrever(display_nome, titulo):
    key = display_nome
    if key in cache:
        print(f"  [cache] {key}")
        return cache[key]

    img_path = gemini_png_para(display_nome)
    if not img_path:
        return "[Imagem nao encontrada para descricao]"

    prompt = (
        f"Descreva em portugues esta tela '{titulo}' de um sistema web: "
        f"objetivo, elementos visiveis e como o usuario interage. Maximo 180 palavras."
    )

    for tentativa in range(3):
        try:
            resp = client.models.generate_content(
                model="gemini-2.5-flash",
                contents=[
                    types.Part.from_bytes(data=img_path.read_bytes(), mime_type="image/png"),
                    prompt,
                ],
            )
            texto = resp.text.strip()
            cache[key] = texto
            salvar_cache()
            print(f"  [OK] {key}")
            return texto
        except Exception as e:
            msg = str(e)
            if "429" in msg or "quota" in msg.lower():
                import re
                m = re.search(r"(\d+)s", msg)
                delay = int(m.group(1)) if m else 60
                print(f"  [429] Quota atingida. Aguardando {delay}s...")
                time.sleep(delay)
            elif "503" in msg or "overloaded" in msg.lower():
                print(f"  [503] Servidor sobrecarregado. Aguardando 30s...")
                time.sleep(30)
            else:
                print(f"  [ERRO] {e}")
                return f"[Descricao indisponivel: {e}]"

    return "[Descricao indisponivel apos 3 tentativas]"


# Indice
linhas = [f"# {nome}", f"\n> Gerado em {data}\n", "## Indice\n"]
for i, r in enumerate(rotas, 1):
    linhas.append(f"{i}. [{r['descricao']}](#{r['descricao'].lower().replace(' ', '-')})")
linhas.append("\n---\n")

# Secoes
for tela_num, r in enumerate(rotas, 1):
    display = shots.get(r["rota"])
    if isinstance(display, list):
        display = display[0] if display else None

    auth_label = " *(requer login)*" if r.get("requer_auth") else ""

    linhas += [
        f"\n## Tela {tela_num} — {r['descricao']}{auth_label}\n",
        f"**Rota:** `{r['rota']}`\n",
    ]

    if not display:
        linhas.append("*Screenshot nao disponivel*\n")
        linhas.append("\n---\n")
        continue

    linhas.append(f"![{r['descricao']}](imagens/{display})\n")
    linhas.append(descrever(display, r["descricao"]))
    linhas.append("\n---\n")

md_path = DOCS / "documentacao.md"
md_path.write_text("\n".join(linhas), encoding="utf-8")

(DOCS / "indice.json").write_text(json.dumps({
    "projeto": nome,
    "gerado_em": data,
    "telas": [
        {
            "tela": i + 1,
            "rota": r["rota"],
            "titulo": r["descricao"],
            "requer_auth": r.get("requer_auth", False),
            "imagem": shots.get(r["rota"], ""),
        }
        for i, r in enumerate(rotas)
    ],
}, indent=2, ensure_ascii=False), encoding="utf-8")

print(f"\n[OK] {md_path}")
