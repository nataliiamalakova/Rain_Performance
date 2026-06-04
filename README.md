# Rain Performance

Інтерактивний звіт по **патернах роботи курʼєрів Kyiv у вихідні** (субота / неділя) за останні 4 тижні.

## Період

- **Суботи:** 2026-05-10, 2026-05-17, 2026-05-24, 2026-05-31
- **Неділі:** 2026-05-11, 2026-05-18, 2026-05-25, 2026-06-01
- **Вибірка:** 13 167 активних курʼєрів з `W23 - Kyiv ENG.csv` (підтверджено в `dim_courier`, city_id=158)

## Метрики

| Метрика | Джерело |
|---|---|
| Courier Online Hours | `fact_courier_daily_v2.courier_total_online_hours` |
| Courier Delivered Orders | `fact_courier_daily_v2.courier_delivered_orders_count` |
| Проміжок доби доставок | `HOUR(order_created_at_local)` (min–max по суботі / неділі) |

**Активний день** = `courier_total_online_hours > 0`.

**«Зазвичай»** = онлайн ≥3 з 4 відповідних вихідних.

## Когорти

1. **Зазвичай обидва вихідні** — ≥3 субот і ≥3 неділь
2. **Зазвичай лише субота** — ≥3 субот, ≤1 неділя
3. **Зазвичай лише неділя** — ≥3 неділь, ≤1 субота
4. **Іноді обидва вихідні** — активність в обидва дні, без стабільного патерну
5. **Іноді лише субота** — 1–2 суботи, без неділь
6. **Іноді лише неділя** — 1–2 неділі, без субот
7. **Зазвичай не працює у вихідні** — 0 субот і 0 неділь з онлайном

## Файли

- `index.html` — інтерактивний звіт (кнопка завантаження CSV по кожній когорті)
- `report_data.json` — сирі дані для звіту
- `build_report.py` — збір даних з Databricks + CSV

## Оновлення

```bash
cd "/Users/nataliia.malakovabolt.eu/Downloads/Session with Jakub H."
./.venv/bin/python3 Rain_Performance/build_report.py
```

Потрібен `.env` з Databricks token у корені workspace (див. `dbx.py`).

## GitHub Pages

Відкрийте `index.html` локально або опублікуйте гілку `main` через GitHub Pages.
