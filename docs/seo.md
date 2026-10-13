# Buscadores e assistentes (SEO e GEO)

Como o site é encontrado, lido e citado por buscadores e por ferramentas de IA, o que ficou fora e como medir. A
mecânica (metadados, conteúdo no HTML, links, assets com hash) está em [Arquitetura](architecture.md#endereços-e-buscadores);
a publicação e a conferência no domínio real, em [Publicação](deploy.md#endereço-público-e-buscadores).

## O que o site entrega

- **Conteúdo no HTML de toda página.** Fichas, votações do Placar, seções, metodologia e `/sobre` chegam com o
  conteúdo essencial dentro de `#app`, montado pelo servidor com as mesmas funções da API. Funciona sem JavaScript,
  e o app mantém esse conteúdo até a API responder. A API continua fora do rastreamento (`robots.txt`): o robô não
  precisa dela para ler a página.
- **Um endereço por coisa.** `/deputado/<id>-<nome>`, `/senador/<id>-<nome>`, `/placar/<id>` e as seções têm
  título, descrição, canonical e dados estruturados próprios. Pares de comparação são compartilháveis, com `noindex`.
  Endereço desconhecido responde 404 em HTML.
- **Links reais** no menu, nas listas e nos cartões; `/politicos` lista todas as fichas; o sitemap lista seções,
  fichas e votações, com a data da revisão de cada votação.
- **Mesmo texto para pessoas, robôs e assistentes.** Títulos, descrições, metodologia e `/sobre` vêm de
  `frontend/data/site-pages.json`, usado pelo servidor e pelo app. `llms.txt` resume o site, as regras de leitura
  dos números e a licença (CC BY 4.0) para quem citar.
- **Compartilhamento.** Imagem padrão em `frontend/static/og-image.png`, gerada de `og-image-source.html`.

Princípios que valem para mudanças futuras: o conteúdo inicial faz parte da interface, com o design existente, e
não é um bloco escondido para buscadores; a camada de SEO formata resultados do backend, nunca recalcula custo,
presença ou alerta; alertas não indicam irregularidade e dado ausente não é zero, também nos metadados; schema só
quando corresponde ao conteúdo visível.

## O que ficou fora, e por quê

- **Imagens de compartilhamento por parlamentar.** Sem biblioteca de imagem no Python; só a imagem padrão.
- **Páginas por município.** Dependem de haver procura (ver abaixo) e de cobertura explicada em cada indicador;
  as coletas do [roadmap](roadmap.md) têm prioridade.
- **Autoria nominal em `/sobre`.** A página diz o que o aviso legal afirma (pessoa física, iniciativa própria);
  nomear a pessoa é decisão do responsável, em `site-pages.json`.
- **Migração de framework, backlinks, textos em massa** e expansão automática para milhares de URLs.

## Como medir

Depois de cada publicação, conferir uma amostra no domínio real (comandos em [Publicação](deploy.md#endereço-público-e-buscadores)).
No Google Search Console e no Bing Webmaster Tools: reenviar o sitemap; inspecionar a home, `/politicos`, uma
ficha e uma votação e confirmar que o HTML renderizado traz o conteúdo; anotar páginas indexadas, impressões,
cliques e consultas, separando buscas pela marca das buscas por parlamentares e temas. Reavaliar em 2–4 semanas
(rastreamento e indexação) e em 6–8 semanas (tráfego e citações no relatório AI Performance do Bing). Um teste
local não mostra o que o Google recebeu; só a inspeção de URL mostra.
