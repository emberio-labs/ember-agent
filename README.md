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

- Конфигурация в одном TOML-файле: системный промпт, провайдер LLM (ключ, модель, base_url), MCP-инструменты.
- Интерактивный диалог в терминале или разовый запрос (`--message`) для скриптов.
- Провайдеры: `mock` (без сети и ключей, для экспериментов и тестов) и `openai`
  (OpenAI и любые OpenAI-совместимые API: OpenRouter, Groq, vLLM, LM Studio и т.п.).
- Модель задаётся провайдеру (`[provider] model`) — как часть «подключения к LLM».
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

[provider]
type = "mock"                  # "mock" | "openai"
model = "gpt-4o-mini"          # модель подключения LLM (для type = "openai")
api_key_env = "OPENAI_API_KEY" # откуда брать ключ (для type = "openai")

[[mcp.servers]]                       # внешние инструменты (опционально)
transport = "stdio"                   # "stdio" | "http"
command = "python"
args = ["path/to/server.py"]
```

Полный пример с комментариями — в [`config.example.toml`](config.example.toml).
Для реального провайдера задайте переменную окружения с ключом, например `OPENAI_API_KEY`.
Если модель не указана, провайдер берёт свою по умолчанию (`gpt-4o-mini` у OpenAI).

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

## Релиз

Публикация новой версии на PyPI автоматизирована через GitHub Actions
(workflow `.github/workflows/publish.yml`):

1. Поднимите версию в `pyproject.toml` (`version = "0.1.0"`) и закоммитьте
   изменение, например: `chore: bump version to 0.1.0`.
2. Создайте и запушьте git-тег, совпадающий с версией:

   ```bash
   git tag v0.1.0
   git push origin v0.1.0
   ```

3. Workflow соберёт wheel и sdist (`poetry build`) и опубликует их на PyPI.
   Ветка `main` при этом не нужна — достаточно тега.

Публикация использует Trusted Publishing (OIDC): секреты в GitHub не хранятся.
Для этого владельцу нужно один раз настроить publisher на PyPI
(и, опционально, на TestPyPI для проверок):

- **PyPI:** https://pypi.org/manage/account/publishing/
- **TestPyPI:** https://test.pypi.org/manage/account/publishing/

Поля формы одинаковы для PyPI и TestPyPI:

| Поле | Значение |
|---|---|
| Project name | `emberio-labs-ember-agent` |
| GitHub owner | `emberio-labs` |
| GitHub repository | `ember-agent` |
| Workflow name | `publish.yml` |
| Environment | *(пусто)* |

После настройки публикацию можно проверить вручную на TestPyPI:
GitHub → Actions → Publish → Run workflow. На боевой PyPI пакет уходит
только по git-тегу `v*`.

## Лицензия

MIT — см. [LICENSE](LICENSE).
