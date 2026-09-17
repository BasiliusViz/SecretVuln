# SecretVuln Frontend

React 19 + TypeScript (Vite 7), react-router 7, react-i18next, Recharts.
Дизайн-система и правила локализации — в [DESIGN.md](DESIGN.md).

## Запуск

```bash
npm install
npm run dev      # http://localhost:5173, /api проксируется на :8000
npm run build    # tsc + vite build → dist/
```

## Структура

```
src/
  main.tsx           # входная точка, подключает i18n и global.css
  App.tsx            # роутер
  i18n/ru.json       # ВСЕ строки интерфейса (в компонентах только t())
  theme/global.css   # CSS-переменные, светлая/тёмная темы ([data-theme])
  theme/severity.ts  # цвета severity для Recharts
  components/        # Layout (сайдбар, переключатель темы), SeverityBadge
  pages/             # Dashboard, Products, Findings, Imports, Roles
```

## Правила

- Ни одной строки UI в компонентах — всё через `t()` и `ru.json`
- Цвета — только CSS-переменные из global.css (иначе сломается тёмная тема);
  исключение — цвета графиков из `theme/severity.ts`
- Severity никогда не кодируется только цветом: цвет + текст + иконка
- Даты/числа — через `Intl` с локалью `ru-RU`
