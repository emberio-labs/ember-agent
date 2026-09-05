# ember-agent

Готовый к запуску агент на базе [`ember`](https://github.com/emberio-labs/ember):
настройка в TOML — запуск одной командой.

- **CLI-команда:** `ember-agent` (короткая, удобная в терминале)
- **На PyPI пакет публикуется как:** `emberio-labs-ember-agent`

```text
$ ember-agent --version
ember-agent 0.1.0
```

## Возможности

- Конфигурация в одном TOML-файле: системный промпт, модель, провайдер, MCP-инструменты.
- Интерактивный диалог в терминале или разовый запрос (`--message`) для скриптов.
- Провайдеры: `mock` (без сети и ключей, для экспериментов и тестов) и `openai`
  (OpenAI и любые OpenAI-совместимые API: OpenRouter, Groq, vLLM, LM Studio и т.п.).
- Инструменты по [MCP](https://modelcontextprotocol.io): `stdio`-процессы и streamable HTTP-серверы.
- Работает на Python 3.12+.

## Установка

Из PyPI:

```bash
pip install emberio-labs-ember-agent
```

Из исходников (Poetry):

```bash
git clone https://github.com/emberio-labs/ember-agent.git
cd ember-agent
poetry install
```

## Настройка

Скопируйте пример конфигурации и отредактируйте под себя:

```bash
cp config.example.toml config.toml
```

Все секции конфигурации опциональны: пустой файл создаст агента на `MockProvider`,
который работает без сети и API-ключей.

```toml
[agent]
system_prompt = "Ты полезный и краткий помощник."   # как агент себя ведёт
model = "gpt-4o-mini"                               # модель по умолчанию

[provider]
type = "mock"          # "mock" | "openai"
api_key_env = "OPENAI_API_KEY"  # откуда брать ключ (для type = "openai")

[[mcp.servers]]                       # внешние инструменты (опционально)
transport = "stdio"                   # "stdio" | "http"
command = "python"
args = ["path/to/server.py"]
```

Полный пример с комментариями — в [`config.example.toml`](config.example.toml).
Для реального провайдера задайте переменную окружения с ключом, например `OPENAI_API_KEY`.

## Запуск

Интерактивный диалог (выход: `exit`, `quit`, `выход` или Ctrl+D/Ctrl+C):

```bash
ember-agent run
```

Разовый запрос — без диалога, удобно для скриптов:

```bash
ember-agent run -m "Привет! Коротко: кто ты?"
```

Явно указать файл конфигурации:

```bash
ember-agent run -c path/to/config.toml
```

Альтернативный запуск через Python (без установки в окружение):

```bash
python -m ember_agent run -m "Привет"
```

## Разработка

```bash
poetry install                      # установка зависимостей (включая dev)
poetry run pytest                   # тесты
poetry run ruff check ember_agent tests   # линтер
poetry run mypy                     # статическая типизация
```

Код в `ember_agent/`, тесты — в `tests/`. Формат конфигурации описан в
[`config.example.toml`](config.example.toml).

## Лицензия

MIT — см. [LICENSE](LICENSE).
