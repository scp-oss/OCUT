# OCUT — OpenCore Update Tool

Инструмент для обновления папки EFI/OC (кексты, OpenCore.efi, Drivers,
тема, миграция config.plist между версиями OpenCore) без ручного
скачивания файлов с GitHub/Dortania и правки config.plist руками.

Интерфейс — нативное десктоп-приложение (`gui.py`, на PySide6).

## Быстрый старт

Команды ниже сами клонируют (или обновляют до последнего коммита) репозиторий
и запускают приложение. Повторный запуск той же команды подтягивает
последние изменения.

### macOS

```bash
curl -fsSL https://raw.githubusercontent.com/scp-oss/OCUT/claude/gifted-thompson-3q1e6m/run.sh | bash
```

Ничего ставить заранее не нужно — `git`/`python3`, если их ещё нет,
`run.sh` попробует поставить сам через Homebrew (или подскажет
`xcode-select --install`, если Homebrew тоже не установлен). Один
пакет ставится сам при первом запуске (`PySide6`, через
`pip install --user`).

### Linux

Та же самая команда, что и для macOS — `run.sh` не содержит ничего
macOS-специфичного:

```bash
curl -fsSL https://raw.githubusercontent.com/scp-oss/OCUT/claude/gifted-thompson-3q1e6m/run.sh | bash
```

Ничего ставить заранее не нужно — `git`/`python3`/`pip`, если их ещё
нет, `run.sh` поставит сам через apt-get/dnf/yum/pacman/zypper/apk —
смотря что найдётся. Если GUI не запускается с
ошибкой про отсутствующие библиотеки Qt (`libEGL.so`, `libxcb-cursor`
и т.п. — типично для минимальных/серверных установок без графического
окружения), доставьте системные пакеты Qt отдельно, `pip` их не ставит:

```bash
sudo apt install libegl1 libxcb-cursor0 libxkbcommon0
```

### Windows

Через PowerShell — аналог `run.sh` для Windows (`curl | bash` там не
работает нативно):

```powershell
irm https://raw.githubusercontent.com/scp-oss/OCUT/claude/gifted-thompson-3q1e6m/run.ps1 | iex
```

Ничего ставить заранее не нужно — `git` и Python, если их ещё нет,
`run.ps1` установит сам через `winget`.

## Что умеет

- **Кексты** — таблица отслеживаемых компонентов: текущая/доступная
  версия (Dortania в приоритете, GitHub как запасной источник),
  подключение в `Kernel → Add`, вкл/выкл, порядок загрузки (кнопки
  Вверх/Вниз + «Применить изменения»), удаление с подтверждением.
  Добавление нового кекста — из каталога (авто-скачивание, как кнопка
  Download в OpenCore Configurator), с диска (уже распакованный .kext)
  или вручную по `owner/repo`.
- **Drivers** — аналогично, для `UEFI → Drivers`.
- **OpenCorePkg** — сравнение текущей/доступной версии, обновление
  `OpenCore.efi`/`Drivers`/`Resources` (темы) выборочно, с бэкапом всей
  папки OC перед каждым применением.
- **Тема** — скачать и применить `Resources/` из любого репозитория с
  подходящей структурой (по умолчанию `acidanthera/OcBinaryData`).
- **Миграция config.plist** — перенос значений в `Sample.plist` новой
  версии OpenCore с отчётом о несовместимостях, без перезаписи текущего
  конфига.

Все сетевые обращения идут через Dortania build-repo в первую очередь
(там же, где и берутся continuous-сборки acidanthera-экосистемы, минуя
лимиты `api.github.com`), с откатом на официальные GitHub-релизы, где
Dortania не отслеживает проект.
