# Labs-IB

Лабораторные работы по информационной безопасности. Основной рабочий контур —
локальный сетевой стенд для Apple Silicon; исходники PNETLab сохранены отдельно.

## Бесплатный локальный стенд

```bash
docker compose up -d --build
```

Локальный стенд работает на Apple Silicon без vendor-образов. `./lab open`
открывает пустое PNETLab-подобное поле: пользователь сам добавляет выключенные
FRR-роутеры и виртуальные ПК, выбирает порты при соединении, запускает ноды и
открывает HTML-консоли. Реализованы Edit, Reload, Wipe, Export CFG, Startup
Configs и Capture. Готовых схем, адресов и настроенных протоколов нет.

```bash
open http://127.0.0.1:8080
docker compose down
```

Команда `docker compose down` останавливает также созданные в конструкторе узлы,
но не удаляет топологию и конфигурации. Следующий `docker compose up -d --build`
восстанавливает ноды, которые до остановки были запущены, а выключенные оставляет
выключенными.

Дополнительные команды-обёртки:

```bash
./lab doctor
./lab test
./lab status
./lab shell Router1
```

Если после перезагрузки остановлена Colima, выполните `colima start` либо
`./lab up`, который запускает её автоматически. Полная инструкция:
[docs/FRR_STAND.md](docs/FRR_STAND.md).

## Исходный PNETLab/vESR

Исходная топология и интеграция Eltex сохранены. Для точного PNETLab/vESR нужен
x86_64-хост с KVM; управление им доступно командами `./lab remote-doctor`,
`./lab remote-deploy` и `./lab remote-open`.

Полная инструкция и честные ограничения: [docs/PNETLAB_SETUP.md](docs/PNETLAB_SETUP.md).
Исследование исходной логики и таблица совместимости:
[docs/PNETLAB_COMPATIBILITY.md](docs/PNETLAB_COMPATIBILITY.md).

## Состав

- `stand/import/Networks-Labs.unl` — проверенная топология из исходного экспорта;
- `stand/vesr/` — шаблоны и скрипт интеграции Eltex vESR;
- `stand/frr/` — визуальный конструктор с PNETLab-подобным lifecycle на FRRouting и Docker;
- `docs/` — исходные методические материалы и инструкция по запуску;
- `infra/labctl/` — Docker-образ управляющего контейнера;
- `data.env.example` — шаблон локальной конфигурации без секретов;
- `other-discipline/ml/` — отдельно отложенные материалы по машинному обучению.
