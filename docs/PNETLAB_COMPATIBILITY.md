# Исследование PNETLab/EVE-NG и модель локального стенда

Дата проверки: 2026-09-03.

## Что было заменено

PNETLab/EVE-NG состоит из двух уровней:

1. Web-панель хранит лабораторию как набор нод, сетей, портов, координат и
   startup-конфигураций.
2. Runtime запускает реальные QEMU/IOL/Docker-процессы и соединяет их порты
   виртуальными L2-сетями.

Это подтверждается официальным EVE-NG API: у ноды есть тип, шаблон, образ,
число Ethernet-интерфейсов, CPU, RAM, консоль, координаты и статус; отдельный
endpoint возвращает все порты и занятые ими network ID. Топология описывает
связи «порт ноды → сеть/порт другой ноды».

Источники:

- [EVE-NG API: ноды, интерфейсы, топология и lifecycle](https://www.eve-ng.net/index.php/how-to-eve-ng-api/)
- [PNETLab: возможности платформы](https://pnetlab.com/pages/documentation)
- [PNETLab: HTML-консоль](https://www.pnetlab.com/pages/documentation?slug=how-to-console-to-devices)

## Жизненный цикл PNETLab/EVE-NG

- `Start` запускает существующую ноду, `Stop` останавливает её без удаления.
- `Wipe` удаляет рабочее состояние/NVRAM или writable snapshot и возвращает
  ноду к базовому образу.
- `Export CFG` извлекает startup-config в объект лаборатории. После wipe такой
  config можно включить и загрузить при следующем старте.
- Для устройств без экспорта конфигурации PNETLab предлагает commit/snapshot
  состояния образа.
- HTML-console открывается кликом по уже запущенной ноде.
- Capture выбирает конкретный интерфейс ноды.

Источники:

- [EVE-NG API: Start, Stop, Wipe и Export](https://www.eve-ng.net/index.php/how-to-eve-ng-api/)
- [PNETLab: сохранение конфигурации лаборатории](https://www.pnetlab.com/pages/documentation?slug=how-to-save-configuration-of-lab)
- [PNETLab: commit и snapshot QEMU/Docker](https://www.pnetlab.com/pages/documentation?slug=commit-image-docker-and-qemu)

## Что представляет собой Eltex vESR в исходной схеме

Репозиторий `alekho/EVE-NG_vESR` не содержит образ vESR. Автор прямо указывает,
что образ надо запросить у Eltex; интеграция лишь добавляет QEMU-шаблон и скрипт
импорта/экспорта конфигурации. Шаблон запускает `x86_64` QEMU с KVM, использует
Telnet, 3072 MB RAM и четыре порта формата `gi1/0/{N}`.

Экран установки в `Vesr.docx` нужен при подготовке исходного qcow2. После
установки PNETLab/EVE-NG фиксирует образ, и обычные новые ноды уже загружаются из
готовой системы. Поэтому в ARM64-эквиваленте эту фазу корректно заменяет сборка
базового FRR-образа командой Compose, а не декоративная имитация установщика.

Источники:

- [Неофициальная интеграция Eltex vESR для EVE-NG](https://github.com/alekho/EVE-NG_vESR)
- [Eltex: Quick Start vESR](https://docs.eltex-co.ru/display/ED23/Quick%2BStart%2BvESR)
- [Eltex: установка vESR и первичная настройка](https://docs.eltex-co.ru/pages/viewpage.action?pageId=578292485)

## Почему нельзя запустить точный vESR локально на Apple Silicon

Исходный vESR — закрытый x86_64-образ, а шаблон требует аппаратного KVM.
Официальные требования PNETLab ориентированы на Intel VT-x/EPT и отдельную VM.
В Docker Desktop/Colima на Apple Silicon Linux-контейнеры работают в ARM64 VM;
они не превращают ARM-процессор в Intel KVM-хост. Полная программная эмуляция
x86 QEMU теоретически возможна, но не даёт совместимого KVM и непригодна как
стабильный многонодовый стенд.

Источник: [PNETLab Hardware requirements](https://www.pnetlab.com/pages/documentation?slug=hardware-requirements).

## Реализованный эквивалент

| Логика исходного стенда | Реализация Labs-IB |
| --- | --- |
| Add a new node | Форма с template, количеством нод, именем, описанием, CPU, RAM и числом Ethernet-портов |
| Eltex vESR template | ARM64 FRRouting с IPv4/IPv6, static, RIP, OSPF и BGP |
| VPCS | Alpine VPC с отдельной CLI для IP, ping, trace, ARP, save и clear |
| Нода сначала выключена | Контейнер создаётся, но не запускается |
| Выбор интерфейсов при соединении | Диалог показывает только свободные `gi1/0/N` или `ethN` |
| Виртуальный кабель | Отдельная изолированная Docker bridge-сеть на каждое соединение |
| Серый/активный кабель | Цвет зависит от состояния обеих нод |
| Start / Stop / Reload | Реальные операции над контейнером с сохранением состояния в проекте |
| HTML Console | Встроенная консоль с prompt, историей команд и многострочной вставкой |
| vESR `commit` / `confirm` | `commit` сохраняет FRR running-config; `confirm` принят как совместимая операция |
| Порты `gi1/0/N` | Показываются на схеме и переводятся в реальные Linux `ethN` |
| Export CFG | Конфигурация сохраняется в именованный startup-config и скачивается как `.cfg` |
| Startup Configs | Просмотр, ручное редактирование, включение/отключение загрузки после wipe |
| Wipe | Пересоздание ноды из чистого базового образа с сохранением кабелей |
| Capture | `tcpdump` выбранного порта: до 20 пакетов или 8 секунд |
| Сохранение лаборатории | Ноды, координаты, кабели, параметры, желаемые состояния и startup-config лежат в Docker volume |

## Граница совместимости

Скопирован рабочий процесс, нужный для `Vesr.docx` и сетевой лабораторной, но не
весь многопользовательский продукт PNETLab. Не реализованы Lab Store, роли,
совместное редактирование, workbook-редактор и vendor-лицензирование.

FRR реализует реальную маршрутизацию и обмен пакетами, но его полный CLI не
тождественен Eltex. Поддержаны привычные имена `gigabitethernet 1/0/N`, команды
`configure`, `commit`, `confirm`, `reload system` и `show interfaces status`;
остальные протоколы настраиваются синтаксисом FRR. Если преподаватель проверяет
именно текст Eltex-команд, нужен настоящий vESR на x86_64/KVM-хосте. Если
проверяются протокол и связность, локальный стенд воспроизводит необходимую
сетевую механику.
