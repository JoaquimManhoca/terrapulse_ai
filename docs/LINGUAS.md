# Línguas — Português, Inglês, Chitewe e Sena

## Estado atual

| Língua | Código | Estado | Revisão nativa |
| --- | --- | --- | --- |
| Português | `pt` | Completo | Sim |
| Inglês | `en` | Completo | Sim |
| Chitewe | `chitewe` | Completo ao nível de chaves | Não |
| Sena | `sena` | Completo ao nível de chaves | Não |

O português é o catálogo de referência (`app/i18n.py`). Os quatro catálogos
têm a mesma lista de chaves e não há valores vazios. Chitewe e Sena cobrem
toda a interface, mas a qualidade linguística ainda é provisória e **não deve**
ser apresentada como definitiva sem revisão nativa.

## Fallback

`get_catalog(lang)` devolve o catálogo português e sobrepõe as chaves da língua
escolhida. Esta protecção mantém-se para evitar chaves em bruto, mas os
catálogos actuais estão completos, pelo que não há mistura de português nas
páginas em inglês, Chitewe ou Sena.

## Áudio

- A leitura usa a Web Speech API do telemóvel.
- Inglês usa `en-US`; português usa `pt-PT`.
- Para Chitewe e Sena não há, em geral, voz local; a aplicação avisa que está a
  ler com a voz padrão.
- A solução definitiva é gravar áudio com falantes nativos e servi-lo como
  ficheiros estáticos.

## Glossário mínimo

| Conceito | Português | Inglês | Chitewe | Sena |
| --- | --- | --- | --- | --- |
| Plantar agora | Planta agora | Plant now | Dyara zvino | Dyala lero |
| Esperar | Espera | Wait | Mira | Linda |
| Risco alto | Risco alto | High risk | Njodzi huru | Ngozi ikulu |
| Chuva | Chuva | Rain | Mvura | Mvura |
| Semente | Semente | Seed | Mbeu | Mbeu |
| Milho | Milho | Maize | Chibage | Chibage |
| Dias secos consecutivos | Dias secos consecutivos | Consecutive dry days | Mazuva akaoma akatevedzana | Mazuva akaoma akatevedzana |
| Ouvir | Ouvir | Listen | Inzwa | Pfa |

## Processo de revisão

1. Um falante nativo de Chitewe ou Sena revê as chaves em `app/i18n.py`.
2. Corrige o texto e confirma o significado agronómico com um técnico local.
3. Só então `LANGUAGES[lang]["reviewed"]` passa a `True`.
4. Adicionar um teste ou nota com a data e o revisor.
5. Repetir para o áudio, com gravação e consentimento.

## Como adicionar ou corrigir chaves

- Editar `TRANSLATIONS` em `app/i18n.py`.
- Manter a mesma chave nos quatro catálogos.
- Evitar texto longo; a interface é para telemóvel e para leitura em voz alta.
- Usar frases curtas e imperativas.
- Não traduzir nomes próprios (TerraPulse AI, NASA, Open-Meteo).

## Testes

`tests/test_i18n.py` verifica:

- paridade e preenchimento de todas as chaves nos quatro catálogos;
- tradução efectiva em inglês, Chitewe e Sena;
- devolução da própria chave quando não existe tradução;
- estado honesto de revisão (`pt` e `en` revistos; `chitewe` e `sena` não
  revistos);
- tradução das páginas principais e dos labels dos gráficos em inglês.

## Aviso

As traduções atuais são um ponto de partida para a demonstração. A validação
linguística é um requisito da Fase 3, não um detalhe opcional.
