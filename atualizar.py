#!/usr/bin/env python3
"""Coletor diário do painel de deputados estaduais (São Paulo, Alesp).

Baixa os arquivos abertos da Alesp, calcula por deputado projetos apresentados,
quantos foram aprovados e presença nas reuniões de comissões, e grava deputados.json.
Só usa a biblioteca padrão do Python.

  python atualizar.py              # coleta completa
  python atualizar.py --saida x.json

Códigos de saída: 0 ok, 1 erro de rede/execução, 2 dados incompletos (validação).
"""
import argparse, bisect, collections, datetime as dt, json, os, re, sys, tempfile, time
import urllib.request, zipfile
import xml.etree.ElementTree as ET

BASE = "https://www.al.sp.gov.br/repositorioDados/"
ARQUIVOS = {
    "deputados": "deputados/deputados.xml",
    "proposituras": "processo_legislativo/proposituras.zip",
    "autores": "processo_legislativo/documento_autor.zip",
    "andamentos": "processo_legislativo/documento_andamento_atual.zip",
    "reunioes": "processo_legislativo/comissoes_permanentes_reunioes.xml",
    "presencas": "processo_legislativo/comissoes_permanentes_presencas.xml",
    "membros": "processo_legislativo/comissoes_membros.xml",
}
UF = "SP"
INICIO_LEGISLATURA = "2023-03-15"      # 20ª legislatura (2023-2027)
LEGISLATURA = 20
# IdNatureza da Alesp: 1 PL, 2 PLC, 3 PR, 4 PDL, 5 PEC
NATUREZAS = {"1": "pl", "2": "plc", "3": "pr", "4": "pdl", "5": "pec"}

RE_LEI = re.compile(r"Publicad[ao] (?:a|o) (?:Lei|Lei Complementar|Decreto Legislativo|Resolu[cç][aã]o|Emenda Constitucional)\b|Promulgad", re.I)
RE_APROVADO = re.compile(
    r"Recebido pelo Governador|Protocolado junto ao gabinete do Senhor Governador|Publicado o Aut[oó]grafo|"
    r"Elabora[cç][aã]o do Aut[oó]grafo|minuta de aut[oó]grafo|Aprovado o Projeto", re.I)
RE_ARQUIVO = re.compile(r"Arquivo - |Arquive-se|Arquivado", re.I)


def baixar(rel, destino, tentativas=4):
    url = BASE + rel
    ult = None
    for t in range(tentativas):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "monitor-deputados-estaduais (GitHub Actions)"})
            with urllib.request.urlopen(req, timeout=180) as r, open(destino, "wb") as f:
                while True:
                    b = r.read(1 << 20)
                    if not b:
                        break
                    f.write(b)
            return destino
        except Exception as e:  # noqa: BLE001
            ult = e
            time.sleep(5 * (t + 1))
    raise RuntimeError("falha ao baixar %s: %s" % (url, ult))


def abrir(caminho):
    """Abre XML puro ou o primeiro XML de um .zip, como fluxo binário."""
    if caminho.endswith(".zip"):
        z = zipfile.ZipFile(caminho)
        return z.open(z.namelist()[0])
    return open(caminho, "rb")


def itens(caminho, tag):
    for _, el in ET.iterparse(abrir(caminho)):
        if el.tag == tag:
            yield el
            el.clear()


def dia(s):
    return (s or "")[:10]


def med(v):
    v = sorted(x for x in v if x is not None)
    if not v:
        return None
    m = len(v) >> 1
    return round(v[m] if len(v) % 2 else (v[m - 1] + v[m]) / 2, 1)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--saida", default=os.path.join(os.path.dirname(os.path.abspath(__file__)), "deputados.json"))
    a = ap.parse_args()
    aqui = os.path.dirname(os.path.abspath(__file__))
    hoje = dt.date.today().isoformat()
    espectro = json.load(open(os.path.join(aqui, "espectro.json"), encoding="utf-8"))
    mapa = espectro["partidos"]

    tmp = tempfile.mkdtemp(prefix="alesp_")
    arq = {k: baixar(v, os.path.join(tmp, os.path.basename(v))) for k, v in ARQUIVOS.items()}

    # --- deputados em exercício
    deps = {}
    for e in itens(arq["deputados"], "Deputado"):
        if e.findtext("Situacao") != "EXE":
            continue
        spl = e.findtext("IdSPL")
        deps[spl] = {"id": int(e.findtext("IdDeputado")), "spl": spl, "nome": (e.findtext("NomeParlamentar") or "").strip(),
                     "partido": (e.findtext("Partido") or "").strip(), "uf": UF}
    if not deps:
        raise RuntimeError("lista de deputados vazia")
    por_idd = {d["id"]: d["spl"] for d in deps.values()}

    # --- projetos da legislatura (PL, PLC, PR, PDL, PEC)
    projetos = {}
    for e in itens(arq["proposituras"], "propositura"):
        nt = e.findtext("IdNatureza")
        ano = e.findtext("AnoLegislativo")
        if nt not in NATUREZAS or not ano or int(ano) < 2023:
            continue
        pub = dia(e.findtext("DtPublicacao"))
        if pub and pub < INICIO_LEGISLATURA:
            continue
        projetos[e.findtext("IdDocumento")] = NATUREZAS[nt]

    autores = collections.defaultdict(set)   # spl -> {IdDocumento}
    n_aut = 0
    for e in itens(arq["autores"], "DocumentoAutor"):
        doc = e.findtext("IdDocumento")
        if doc in projetos:
            n_aut += 1
            spl = e.findtext("IdAutor")
            if spl in deps:
                autores[spl].add(doc)

    # --- situação: lei, aprovado na Alesp, arquivado
    lei, aprov, arquivo = set(), set(), set()
    for e in itens(arq["andamentos"], "DocumentoAndamento"):
        doc = e.findtext("IdDocumento")
        if doc not in projetos:
            continue
        desc = e.findtext("Descricao") or ""
        etapa = e.findtext("NmEtapa") or ""
        if RE_LEI.search(desc):
            lei.add(doc)
        if RE_APROVADO.search(desc):
            aprov.add(doc)
        if etapa == "Arquivo" or RE_ARQUIVO.search(desc):
            arquivo.add(doc)

    # --- reuniões de comissões realizadas na legislatura
    reuniao = {}                              # IdReuniao -> (comissão, data)
    for e in itens(arq["reunioes"], "ReuniaoComissao"):
        d = dia(e.findtext("Data"))
        if e.findtext("Situacao") == "REALIZADA" and INICIO_LEGISLATURA <= d <= hoje:
            reuniao[e.findtext("IdReuniao")] = (e.findtext("IdComissao"), d)
    presente = collections.defaultdict(set)   # spl -> {IdReuniao}
    com_registro = set()                      # reuniões com lista de presença preenchida
    casou_id = nao_casou = 0
    for e in itens(arq["presencas"], "ReuniaoComissaoPresenca"):
        rid = e.findtext("IdReuniao")
        if rid not in reuniao:
            continue
        com_registro.add(rid)
        idd = e.findtext("IdDeputado")
        spl = idd if idd in deps else por_idd.get(int(idd)) if idd and idd.isdigit() else None
        if spl is None:
            nao_casou += 1
            continue
        casou_id += 1
        presente[spl].add(rid)

    # só reuniões com lista de presença entram na conta (sem lista, não dá para saber quem faltou)
    por_comissao = collections.defaultdict(list)
    for rid in com_registro:
        c, d = reuniao[rid]
        por_comissao[c].append((d, rid))
    for c in por_comissao:
        por_comissao[c].sort()

    janelas = collections.defaultdict(dict)   # spl -> {comissão: (início, fim)} só como membro efetivo
    for e in itens(arq["membros"], "MembroComissao"):
        spl = e.findtext("IdMembro")
        if spl not in deps or e.findtext("Efetivo") != "S":
            continue
        ini = max(dia(e.findtext("DataInicio")) or INICIO_LEGISLATURA, INICIO_LEGISLATURA)
        fim = dia(e.findtext("DataFim")) or hoje
        if fim < INICIO_LEGISLATURA:
            continue
        c = e.findtext("IdComissao")
        j = janelas[spl].get(c)
        janelas[spl][c] = (min(ini, j[0]), max(fim, j[1])) if j else (ini, fim)

    # --- indicadores por deputado
    saida, sem_dados = [], 0
    for spl, d in deps.items():
        meus = autores.get(spl, set())
        cont = collections.Counter(projetos[x] for x in meus)
        n_lei = sum(1 for x in meus if x in lei)
        n_apr = sum(1 for x in meus if x in aprov and x not in lei)
        n_enc = sum(1 for x in meus if x not in lei and x not in aprov and x in arquivo)
        n_tr = len(meus) - n_lei - n_apr - n_enc
        todas = set()
        for c, (ini, fim) in janelas.get(spl, {}).items():
            lst = por_comissao.get(c, [])
            i = bisect.bisect_left(lst, (ini, ""))
            j = bisect.bisect_right(lst, (fim, "~"))
            todas.update(rid for _, rid in lst[i:j])
        n_reu = len(todas)
        n_pres = len(todas & presente.get(spl, set()))
        d.update({
            "foto": "",
            "espectro": mapa.get(d["partido"], "centro"),
            "reunioes": n_reu, "presencas": n_pres, "faltas": n_reu - n_pres,
            "presenca_pct": round(100 * n_pres / n_reu, 1) if n_reu else None,
            "comissoes": len(janelas.get(spl, {})),
            "projetos": len(meus), "leis": n_lei, "aprovados_casa": n_apr, "aprovados": n_lei + n_apr,
            "encerrados": n_enc, "tramitando": n_tr,
            "pl": cont["pl"], "plc": cont["plc"], "pr": cont["pr"], "pdl": cont["pdl"], "pec": cont["pec"],
            "aprovados_pct": round(100 * (n_lei + n_apr) / len(meus), 1) if meus else 0.0,
            "leis_pct": round(100 * n_lei / len(meus), 1) if meus else 0.0,
        })
        if not n_reu and not meus:
            sem_dados += 1
        saida.append(d)

    # --- validações: se faltar muito dado, falha e não publica
    erros = []
    if len(saida) < 80:
        erros.append("poucos deputados (%d)" % len(saida))
    if sem_dados > 0.1 * len(saida):
        erros.append("deputados sem nenhum dado: %d" % sem_dados)
    if len(projetos) < 2000:
        erros.append("poucos projetos (%d)" % len(projetos))
    if len(com_registro) < 100:
        erros.append("poucas reuniões de comissão com presença (%d)" % len(com_registro))
    if casou_id < 1000:
        erros.append("presenças casadas com deputados: %d (nao casou: %d)" % (casou_id, nao_casou))
    if erros:
        print("VALIDAÇÃO FALHOU: " + "; ".join(erros), file=sys.stderr)
        sys.exit(2)

    grupos = {}
    for g in ("esquerda", "centro", "direita"):
        s = [x for x in saida if x["espectro"] == g]
        grupos[g] = {"deputados": len(s), "projetos_total": sum(x["projetos"] for x in s),
                     "projetos_mediana": med([x["projetos"] for x in s]), "presenca_mediana": med([x["presenca_pct"] for x in s]),
                     "aprovados_total": sum(x["aprovados"] for x in s), "leis_total": sum(x["leis"] for x in s)}
    ultima = max((d for d, _ in (v for lst in por_comissao.values() for v in lst)), default=hoje)
    meta = {"atualizado_em": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
            "dados_ate": ultima, "uf": UF, "estado": "São Paulo", "casa": "Assembleia Legislativa de São Paulo (Alesp)",
            "legislatura": LEGISLATURA, "reunioes_comissoes": len(com_registro), "total_projetos": len(projetos),
            "fonte": "Dados Abertos da Alesp", "espectro_nota": espectro.get("nota", ""), "grupos": grupos, "total_deputados": len(saida)}
    saida.sort(key=lambda x: x["nome"].lower())
    tmp_out = a.saida + ".tmp"
    with open(tmp_out, "w", encoding="utf-8") as f:
        json.dump({"meta": meta, "deputados": saida}, f, ensure_ascii=False, separators=(",", ":"))
    os.replace(tmp_out, a.saida)
    print("ok: %d deputados, %d projetos (%d aprovados, %d leis), %d reuniões; autores/projeto=%.1f; presenças casadas=%d, nao=%d" % (
        len(saida), sum(x["projetos"] for x in saida), sum(x["aprovados"] for x in saida), sum(x["leis"] for x in saida),
        len(reuniao), n_aut / max(len(projetos), 1), casou_id, nao_casou))


if __name__ == "__main__":
    try:
        main()
    except SystemExit:
        raise
    except Exception as e:  # noqa: BLE001
        print("ERRO: %s" % e, file=sys.stderr)
        sys.exit(1)
