# Capacidade e teste de carga

Como medir quanto tráfego o site aguenta, o que foi medido em outubro de 2026 e onde estão os limites.
O servidor é o `backend.server --prod` descrito em [Publicação](deploy.md): Python puro, uma thread por
conexão, SQLite e cache de respostas em memória, atrás de um Cloudflare Tunnel num VPS de 1 vCPU e 2 GB.

## Como medir

A ferramenta usada foi o [oha](https://github.com/hatoo/oha) (`brew install oha`), que abre N conexões
simultâneas com keep-alive e mede req/s, percentis de latência e erros. `scripts/load_test_urls.py`
imprime uma lista de URLs com pesos a partir da base e dos snapshots locais, simulando um pico de
visitas: home e seções, fichas de 40 parlamentares, fotos, Placar, buscas de cidade e perfis. A
repetição de uma linha é o seu peso.

```sh
python3 scripts/load_test_urls.py http://127.0.0.1:8000 > /tmp/urls.txt
make prod   # em outro terminal; o modo --prod é o que vai ao ar
oha -z 20s -c 500 -H 'Accept-Encoding: gzip' --urls-from-file /tmp/urls.txt
```

Uma rota só: `oha -z 10s -c 1000 -H 'Accept-Encoding: gzip' http://127.0.0.1:8000/api/c/politicos`.

Contra o site publicado, suba a concorrência aos poucos (50, 100, 200) e pare quando aparecerem
erros ou o p95 passar de alguns segundos: o teste compete com os visitantes reais e o VPS é pequeno.
Fotos ainda não baixadas são buscadas na Câmara na primeira visita, então a primeira rodada é mais lenta.

No macOS, `kern.ipc.somaxconn` (128) limita a fila de conexões do kernel; acima de algumas centenas de
conexões abertas de uma vez, parte delas recebe `timeout` de conexão no cliente. Isso é do Mac, não do
servidor: no Linux a fila pedida pelo servidor (1024) vale.

## O que foi medido (outubro de 2026)

Mac de 8 núcleos, base real, cenário de pico com tráfego misto, 20 s por nível. Antes e depois das
mudanças descritas em [Publicação](deploy.md#o-que-o-modo---prod-muda): gzip guardado no cache,
cálculo único por chave, fila de conexões, cache das rotas de snapshot e vagas de cálculo.

| Conexões simultâneas | Antes | Depois |
|---|---|---|
| 1000, cache vazio (rajada) | 293 req/s, 44% de falhas | 2.101 req/s, 0,8% de falhas (50 respostas "ocupado") |
| 500 | 226 req/s, p95 3,7 s, 25% de falhas | 5.595 req/s, p95 0,23 s, sem falhas |
| 1000 | 221 req/s, p95 6,5 s, 64% de falhas | 3.539 req/s, p95 0,57 s, 1,5% (timeouts de conexão do Mac) |
| 3000 | 827 req/s, p95 2,6 s, 50% de falhas | 4.507 req/s, p95 0,51 s, 7,9% (idem) |

Por rota, a 1000 conexões: home de 460 para 8.900 req/s (o gzip de 814 KB era refeito a cada visita);
Placar de 380 para 1.200; busca de cidades de 263 para 620 em consultas variadas; rotas do SQLite já em
cache, de 8.800 para 13.000. Memória do processo com todos os snapshots carregados: cerca de 700 MB,
antes e depois; é o custo de manter `cities.json`, `perfis.json`, contas e emendas em memória.

Site publicado, código anterior, de uma única origem, com o Cloudflare sem guardar nada em cache:

| Conexões | Resultado |
|---|---|
| 50 | 39 req/s, p50 1,1 s, p95 2,5 s, duas respostas 503 |
| 100 | 46 req/s, p50 1,6 s, p95 4,5 s; teste interrompido |

Ou seja, o VPS saturava por volta de 40 a 50 req/s do cenário misto. Cada conexão do teste pede sem
parar; um visitante real faz algumas requisições e lê, então 50 conexões correspondem a algumas centenas
de pessoas ao mesmo tempo.

Mesmo dia, depois de publicar as mudanças e ligar a regra de cache do Cloudflare (abaixo):

| Conexões | Resultado |
|---|---|
| 50 | 306 req/s, p50 33 ms, p95 0,96 s, sem falhas |
| 100 | 1.085 req/s, p50 54 ms, p95 0,25 s, sem falhas |
| 200 | 1.087 req/s, p50 106 ms, p95 0,50 s, sem falhas |
| 400 | 1.020 req/s, p50 208 ms, p95 1,2 s, sem falhas |
| 800 | 903 req/s, p50 373 ms, p95 3,4 s, dois timeouts; teste interrompido |

O patamar de cerca de 1.000 req/s e 65 MB/s a partir de 100 conexões é o limite de uma única origem de
teste (um Mac, uma conexão de internet, um IP) e da borda, não do VPS: a latência cresce com as conexões
sem que apareçam erros, e `/healthz` respondeu em menos de 0,1 s logo depois. Para medir além disso seria
preciso gerar carga de vários pontos ao mesmo tempo.

## Limites conhecidos e o que fazer num pico

- **Cloudflare sem cache.** Em outubro de 2026 todas as respostas saíam com `cf-cache-status: DYNAMIC`:
  o Cloudflare só guarda extensões estáticas por padrão, e as páginas, a API e as fotos (`/api/c/foto/…`,
  sem extensão) iam todas ao VPS. Uma regra de cache no painel do Cloudflare (Caching → Cache Rules:
  hostname igual ao domínio, *Eligible for cache*, Edge TTL "respeitar o Cache-Control da origem")
  faz a borda servir o que o servidor já marca como `public, max-age=…`: páginas por 60 s, API por 300 s,
  fotos por 7 dias. CSV, `/healthz` e erros saem com `no-store` e continuam passando. É a maior
  alavanca para um pico: o VPS passa a receber uma fração das visitas.
- **1 vCPU.** O servidor Python usa um núcleo de fato (GIL), e o `cloudflared` divide a mesma CPU.
  As respostas em cache custam pouco; o que pesa é a primeira visita de cada página depois da troca
  diária do banco (às 5h40), quando o cache esvazia. As vagas de cálculo e a resposta "ocupado"
  existem para esse momento: o site degrada em fila ordenada em vez de travar.
- **Uma thread por conexão.** Milhares de conexões abertas ao mesmo tempo viram milhares de threads.
  Pelo túnel isso corresponde a requisições em andamento, não a visitantes; conexões paradas são
  fechadas pelo túnel em 90 s e pelo servidor em 120 s.
- **Memória.** 2 GB no VPS, cerca de 700 MB do servidor com todos os snapshots em memória, mais o
  túnel e os jobs de coleta. Um snapshot muito maior que os atuais merece conferência de memória.
