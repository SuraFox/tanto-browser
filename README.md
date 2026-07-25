# tanto-browser

Минималистичный браузер на PyQt6 + QtWebEngine в стиле **tanto**: почти
монохром, один акцент, никаких тулбаров. Вертикальные вкладки в сайдбаре,
адресная строка снизу, любые панели прячутся вплоть до zen-режима.

Не vimlike — управление стандартное, как в любом браузере.

## Возможности

- **Сайдбар с вертикальными вкладками** — акцентная черта у активной,
  закрытие по ×/средней кнопке, drag-reorder, зона загрузок.
- **Адресная строка снизу** с живыми подсказками (история + DuckDuckGo),
  выпадающими вверх; `⚠ http` для незащищённых, прогресс загрузки.
- **Скрытие панелей** — `Ctrl+B` сайдбар, `Ctrl+Shift+B` адреска,
  `Ctrl+Shift+Z` zen (обе); у скрытых — peek левого края и оверлей адрески.
- **Adblock** — сетевой блокировщик на фильтр-листах EasyList / EasyPrivacy /
  Peter Lowe / AdGuard (~166k доменов, ~0.0014 мс/запрос), счётчик `⦸`,
  тоггл `Ctrl+Shift+A`. Опциональная косметическая фильтрация.
- **Темы** — `black` / `white`, сайтам передаётся `prefers-color-scheme`.
- **Импорт кук из Helium** — `tanto-browser --import-helium`.
- Персистентный профиль, восстановление сессии, самоподписанные
  сертификаты для приватных хостов (Proxmox и пр.), find-bar, зум.

## Горячие клавиши

| | |
|---|---|
| `Ctrl+T` / `Ctrl+W` | новая / закрыть вкладку |
| `Ctrl+Tab` / `Ctrl+1..9` | переключение вкладок |
| `Ctrl+L` | адресная строка |
| `Ctrl+F` / `F3` | поиск по странице |
| `Alt+←` / `Alt+→` | назад / вперёд |
| `Ctrl+R` | обновить |
| `Ctrl+B` / `Ctrl+Shift+B` / `Ctrl+Shift+Z` | сайдбар / адреска / zen |
| `Ctrl+Shift+A` | adblock вкл/выкл |
| `Ctrl+=` / `Ctrl+-` / `Ctrl+0` | зум |

## Запуск из исходников

```sh
pip install -r requirements.txt
python tanto_browser.py
```

Требуется Python 3.11+.

## Готовые сборки

Собранные бинарники для **Linux** и **Windows** — во вкладке
[Releases](../../releases) и в артефактах
[GitHub Actions](../../actions). Windows-сборку нельзя кросс-компилировать
из Linux, поэтому она собирается на windows-раннере в CI.

Локальная сборка (под текущую ОС):

```sh
pip install pyinstaller
pyinstaller --noconfirm tanto-browser.spec
# результат в dist/tanto-browser/
```

## Конфигурация

`~/.config/tanto-browser/config.json`:

| ключ | значение |
|---|---|
| `theme` | `black` \| `white` |
| `adblock` | `true` \| `false` |
| `adblock_cosmetic` | `true` \| `false` (косметика, по умолчанию off) |

Профиль и кеш: `~/.local/share/tanto-browser/`.

## Заметки

QtWebEngine не запускает Chromium-расширения (нет WebExtensions API),
поэтому uBlock/AdGuard как `.crx` подключить нельзя — вместо этого
используются те же фильтр-листы через сетевой перехватчик.

## Лицензия

MIT
