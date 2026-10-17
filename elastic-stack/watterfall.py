#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
waterfall.py - Gera a linha do tempo (waterfall) de um trace do Elastic APM
a partir dos documentos gravados no Elasticsearch.

Uso tipico (no WSL, com a stack no ar e depois de chamar /api/lento):
    python3 waterfall.py
    python3 waterfall.py --route "GET /api/lento" --pick slowest
    python3 waterfallpy --trace-id <TRACE_ID>
    python3 waterfall.py --desde 2026-10-04T23:00:00Z --ate 2026-10-05T03:00:00Z --pick slowest
    python3 waterfall.py --erro            # imprime o ultimo erro com stack trace

Dependencias: Python 3.8+ e matplotlib (pip install matplotlib).
Nao usa bibliotecas HTTP externas (apenas urllib).
"""
import argparse
import csv
import json
import sys
import urllib.request
import urllib.error
from datetime import datetime


# ---------------------------------------------------------------- utilidades
def get(doc, path, default=None):
    """Le um campo por caminho 'a.b.c', aceitando _source aninhado ou plano."""
    if path in doc:
        return doc[path]
    cur = doc
    for part in path.split("."):
        if isinstance(cur, dict) and part in cur:
            cur = cur[part]
        else:
            return default
    return cur


def es_search(base, index, body):
    url = f"{base.rstrip('/')}/{index}/_search"
    req = urllib.request.Request(
        url, data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        sys.exit(f"Erro HTTP {e.code} em {url}:\n{e.read().decode('utf-8', 'replace')[:800]}")
    except urllib.error.URLError as e:
        sys.exit(f"Não foi possível conectar em {base}: {e.reason}\n"
                 "Confira se o container do Elasticsearch está 'Up' (docker compose ps).")


def ts_us(doc):
    """Inicio do evento em microssegundos (epoch)."""
    v = get(doc, "timestamp.us")
    if v is not None:
        return int(v)
    iso = get(doc, "@timestamp")
    if iso:
        dt = datetime.fromisoformat(str(iso).replace("Z", "+00:00"))
        return int(dt.timestamp() * 1_000_000)
    return 0


def fmt_ms(us):
    """Formata microssegundos como milissegundos com virgula decimal (pt-BR)."""
    ms = us / 1000.0
    s = f"{ms:,.1f}"
    return s.replace(",", "X").replace(".", ",").replace("X", ".") + " ms"


# ------------------------------------------------------------- busca do trace
def find_trace_id(args):
    janela = []
    if args.desde or args.ate:
        rng = {}
        if args.desde:
            rng["gte"] = args.desde
        if args.ate:
            rng["lt"] = args.ate
        janela = [{"range": {"@timestamp": rng}}]
    # event.duration (ns) existe em transações e spans; os spans não têm transaction.name
    sort = ([{"event.duration": "desc"}] if args.pick == "slowest"
            else [{"@timestamp": "desc"}])

    def consulta(filtro_nome):
        body = {"size": 1, "sort": sort,
                "query": {"bool": {"filter": [filtro_nome] + janela}}}
        return es_search(args.es, args.index, body).get("hits", {}).get("hits", [])

    # transaction.name é text com subcampo .keyword (índices sem data stream)
    hits = consulta({"term": {"transaction.name.keyword": args.route}})
    if not hits:
        hits = consulta({"match_phrase": {"transaction.name": args.route}})
    if not hits:
        sys.exit(f"Nenhuma transação '{args.route}' encontrada em '{args.index}'"
                 + (" na janela informada" if janela else "") + ".\n"
                 "Confira o nome da rota (Discover > transaction.name), o índice "
                 "e a janela --desde/--ate (UTC).")
    return get(hits[0]["_source"], "trace.id")


def fetch_trace(args, trace_id):
    body = {
        "size": 1000,
        "sort": [{"@timestamp": "asc"}],
        "query": {"match_phrase": {"trace.id": trace_id}},
    }
    res = es_search(args.es, args.index, body)
    return [h["_source"] for h in res.get("hits", {}).get("hits", [])]


# --------------------------------------------------------- montagem das linhas
def dur_us(d, fallback_field):
    """Duração em µs: event.duration (ns, padrão do APM Server 8) ou campo .us."""
    ns = get(d, "event.duration")
    if ns is not None:
        return int(ns) // 1000
    return int(get(d, fallback_field, 0))


def build_rows(docs):
    """Converte documentos do APM em linhas (transação/spans) com início e duração.

    No APM Server 8 a transação também tem span.id (igual a transaction.id); por isso a
    classificação usa o nome: só a transação tem transaction.name, só o span tem span.name.
    """
    rows = []
    for d in docs:
        if get(d, "transaction.name"):
            rows.append({
                "kind": "transaction",
                "id": get(d, "transaction.id"),
                "parent": get(d, "parent.id"),
                "name": get(d, "transaction.name"),
                "start_us": ts_us(d),
                "dur_us": dur_us(d, "transaction.duration.us"),
            })
        elif get(d, "span.name") or get(d, "span.type"):
            rows.append({
                "kind": "span",
                "id": get(d, "span.id"),
                "parent": get(d, "parent.id"),
                "name": get(d, "span.name") or get(d, "span.type"),
                "start_us": ts_us(d),
                "dur_us": dur_us(d, "span.duration.us"),
            })
    if not rows:
        return rows
    t0 = min(r["start_us"] for r in rows)
    by_id = {r["id"]: r for r in rows if r["id"]}

    def depth(r, seen=()):
        p = r["parent"]
        if not p or p not in by_id or p in seen:
            return 0
        return 1 + depth(by_id[p], seen + (p,))

    for r in rows:
        r["offset_us"] = r["start_us"] - t0
        r["depth"] = depth(r)
    rows.sort(key=lambda r: (r["offset_us"], r["depth"]))
    return rows


# -------------------------------------------------------------------- saidas
def print_table(rows, trace_id):
    print(f"\ntrace.id: {trace_id}\n")
    print(f"{'tipo':<12}{'início (ms)':>13}{'duração':>14}   nome")
    for r in rows:
        print(f"{r['kind']:<12}{r['offset_us']/1000:>13.1f}{fmt_ms(r['dur_us']):>14}   "
              f"{'  ' * r['depth']}{r['name']}")
    print()


def save_csv(rows, path):
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["tipo", "nome", "inicio_ms", "duracao_ms", "id", "parent_id"])
        for r in rows:
            w.writerow([r["kind"], r["name"], r["offset_us"] / 1000,
                        r["dur_us"] / 1000, r["id"], r["parent"]])


def draw(rows, trace_id, out_path, dpi=200):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    n = len(rows)
    fig, ax = plt.subplots(figsize=(11, 1.6 + 0.55 * n))
    colors = {"transaction": "#3b6fb6", "span": "#e08a2e"}
    total_ms = max((r["offset_us"] + r["dur_us"]) for r in rows) / 1000.0

    for i, r in enumerate(rows):
        y = n - 1 - i
        left = r["offset_us"] / 1000.0
        width = max(r["dur_us"] / 1000.0, total_ms * 0.003)  # barra minima visivel
        ax.barh(y, width, left=left, height=0.55, color=colors[r["kind"]])
        label = fmt_ms(r["dur_us"])
        if width > total_ms * 0.18:
            ax.text(left + width / 2, y, label, ha="center", va="center",
                    color="white", fontsize=9, fontweight="bold")
        else:
            ax.text(left + width + total_ms * 0.01, y, label, ha="left",
                    va="center", fontsize=9)

    ax.set_yticks(range(n))
    ax.set_yticklabels([(("   " * (r["depth"] - 1)) + "└ " if r["depth"] else "") + r["name"] for r in reversed(rows)], fontsize=9)
    ax.set_xlim(0, total_ms * 1.12)
    ax.set_xlabel("Tempo desde o início do trace (ms)")
    ax.xaxis.grid(True, linestyle=":", alpha=0.5)
    ax.set_axisbelow(True)
    for s in ("top", "right"):
        ax.spines[s].set_visible(False)

    main = rows[0]["name"]
    ax.set_title(f"Linha do tempo do trace: {main}\ntrace.id {trace_id}",
                 fontsize=11, loc="left")
    from matplotlib.patches import Patch
    ax.legend(handles=[Patch(color=colors["transaction"], label="Transação"),
                       Patch(color=colors["span"], label="Span")],
              loc="lower right", bbox_to_anchor=(1.0, 1.0), ncol=2, frameon=False, fontsize=9)
    fig.text(0.01, 0.005,
             "Fonte: documentos do índice traces-apm* (Elasticsearch 8.12.2); gráfico gerado pela autora (2026).",
             fontsize=8, color="#555555")
    fig.tight_layout(rect=(0, 0.03, 1, 1))
    fig.savefig(out_path, dpi=dpi)
    plt.close(fig)


# ------------------------------------------------------------------ erro/stack
def show_error(args):
    body = {"size": 1, "sort": [{"@timestamp": "desc"}], "query": {"match_all": {}}}
    hits = es_search(args.es, args.error_index, body).get("hits", {}).get("hits", [])
    if not hits:
        sys.exit(f"Nenhum erro encontrado em '{args.error_index}'. "
                 "Ajuste --error-index (Discover > _index de um documento de erro).")
    d = hits[0]["_source"]
    ex = get(d, "error.exception")
    if isinstance(ex, list):
        ex = ex[0] if ex else {}
    ex = ex or {}
    print("@timestamp :", get(d, "@timestamp"))
    print("serviço    :", get(d, "service.name"))
    print("trace.id   :", get(d, "trace.id"))
    print("mensagem   :", get(ex, "message"))
    print("tipo       :", get(ex, "type"))
    print("culprit    :", get(d, "error.culprit"))
    frames = get(ex, "stacktrace") or []
    print("\nstack trace:")
    for fr in frames[:15]:
        print(f"  {get(fr, 'filename', '?')}:{get(fr, 'line.number', '?')}  "
              f"em {get(fr, 'function', '?')}")


# ------------------------------------------------------------------------ main
def main():
    ap = argparse.ArgumentParser(description="Waterfall de trace do Elastic APM (a partir do Elasticsearch).")
    ap.add_argument("--es", default="http://localhost:9200", help="URL do Elasticsearch")
    ap.add_argument("--index", default="traces-apm*", help="indice/data stream de traces")
    ap.add_argument("--error-index", default="logs-apm.error*", help="indice/data stream de erros")
    ap.add_argument("--route", default="GET /api/lento", help="nome da transacao")
    ap.add_argument("--pick", choices=["latest", "slowest"], default="latest",
                    help="qual transacao usar quando ha varias")
    ap.add_argument("--trace-id", help="usa este trace.id (ignora --route)")
    ap.add_argument("--desde", help="início da janela em UTC, ex.: 2026-10-04T23:00:00Z")
    ap.add_argument("--ate", help="fim da janela em UTC, ex.: 2026-10-05T03:00:00Z")
    ap.add_argument("--out", default="waterfall_api_lento.png", help="PNG de saida")
    ap.add_argument("--csv", help="salva tambem a tabela em CSV")
    ap.add_argument("--erro", action="store_true", help="mostra o ultimo erro com stack trace e sai")
    args = ap.parse_args()

    if args.erro:
        show_error(args)
        return

    trace_id = args.trace_id or find_trace_id(args)
    docs = fetch_trace(args, trace_id)
    rows = build_rows(docs)
    if not rows:
        sys.exit(f"O trace {trace_id} não tem transação/spans no índice '{args.index}'.")
    print_table(rows, trace_id)
    if args.csv:
        save_csv(rows, args.csv)
        print(f"CSV salvo em {args.csv}")
    draw(rows, trace_id, args.out)
    print(f"Imagem salva em {args.out}")


if __name__ == "__main__":
    main()