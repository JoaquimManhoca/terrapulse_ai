# Línguas — Português, Chitewe e Sena

## Estado atual

| Língua | Código | Estado | Revisão nativa |
| --- | --- | --- | --- |
| Português | `pt` | Completo | Sim |
| Chitewe | `chitewe` | Provisório | Não |
| Sena | `sena` | Provisório | Não |

O português é o catálogo de referência (`app/i18n.py`). Chitewe e Sena cobrem
apenas as chaves mais visíveis; qualquer chave em falta recai automaticamente
no português. As traduções provisórias **não devem** ser apresentadas como
definitivas.

## Fallback

`get_catalog(lang)` devolve o catálogo português e sobrepõe as chaves da língua
escolhida. Isto garante que a interface nunca mostra chaves em bruto, mas também
 significa que uma página pode misturar português e língua local enquanto a
tradução estiver incompleta.

## Áudio

- A leitura usa a Web Speech API do telemóvel.
- A voz preferida é `pt-PT`; para Chitewe e Sena não há, em geral, voz local.
- Quando a língua não é português, a aplicação avisa que está a ler em
  português.
- A solução definitiva é gravar áudio com falantes nativos e servi-lo como
  ficheiros estáticos.

## Glossário mínimo

| Conceito | Português | Chitewe | Sena |
| --- | --- | --- | --- |
| Plantar agora | Planta agora | Dyara zvino | Dyala lero |
| Esperar | Espera | Mira | Linda |
| Risco alto | Risco alto | Njodzi huru | Ngozi ikulu |
| Chuva | Chuva | Mvura | Mvura |
| Semente | Semente | Mbeu | Mbeu |
| Milho | Milho | Chibage | Chibage |
| Dias secos consecutivos | Dias secos consecutivos | Mazuva akaoma akatevedzana | Mazuva akaoma akatevedzana |
| Ouvir | Ouvir | Inzwa | Pfa |

## Processo de revisão

1. Um falante nativo de Chitewe ou Sena revê as chaves em `app/i18n.py`.
2. Corrige o texto e confirma o significado agronómico com um técnico local.
3. Só então `LANGUAGES[lang]["reviewed"]` passa a `True`.
4. Adicionar um teste ou nota com a data e o revisor.
5. Repetir para o áudio, com gravação e consentimento.

## Como adicionar ou corrigir chaves

- Editar `TRANSLATIONS` em `app/i18n.py`.
- Manter a mesma chave nos três catálogos quando possível.
- Evitar texto longo; a interface é para telemóvel e para leitura em voz alta.
- Usar frases curtas e imperativas.
- Não traduzir nomes próprios (TerraPulse AI, NASA, Open-Meteo).

## Testes

`tests/test_i18n.py` verifica:

- presença das chaves essenciais nas três línguas;
- fallback para português;
- devolução da própria chave quando não existe tradução;
- estado honesto de revisão (`pt` revisto; `chitewe` e `sena` não revistos).

## Aviso

As traduções atuais são um ponto de partida para a demonstração. A validação
linguística é um requisito da Fase 3, não um detalhe opcional.
