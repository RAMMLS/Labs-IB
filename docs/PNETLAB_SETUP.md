# Запуск сетевого стенда PNETLab с Mac

> Если важны протоколы и связность, а не конкретный Eltex CLI, используйте
> бесплатный пустой конструктор FRR: [FRR_STAND.md](FRR_STAND.md).

## Коротко

Mac с Apple Silicon используется как клиент и запускает управляющий Docker-контейнер. Сам PNETLab Box запускается на x86_64-хосте с KVM/VT-x/AMD-V. Это обязательное условие для QEMU-узлов и Eltex vESR.

```bash
cp data.env.example data.env
# заполнить PNETLAB_HOST и способ SSH-доступа
./lab remote-doctor
./lab remote-deploy
./lab remote-open
```

В локальном `data.env` уже можно держать параметры доступа. Файл игнорируется Git и не должен отправляться в репозиторий.

## Почему не PNETLab внутри Docker на Apple Silicon

Контейнер не эмулирует отсутствующий процессор и не создаёт аппаратную nested virtualization. Шаблон vESR использует `qemu_arch: x86_64` и `accel=kvm`. Официальная документация PNETLab требует Intel VT-x/EPT и отдельно предупреждает, что без виртуализации QEMU-ноды не запускаются. EVE-NG прямо относит Mac на M-series к неподдерживаемым системам из-за VMware Fusion и nested CPU.

Программная x86-эмуляция через QEMU/UTM технически способна загрузить отдельную VM, но вложенный сетевой стенд из множества QEMU-узлов будет непригодно медленным и не является рабочим вариантом для лабораторной.

## Что требуется от x86-хоста

- `x86_64` Intel/AMD;
- включённые VT-x/AMD-V и nested virtualization;
- доступный `/dev/kvm` внутри PNETLab Box;
- минимум 8 ГБ RAM и 40 ГБ диска для базовой установки; для полной топологии из 103 узлов потребуется существенно больше;
- установленная PNETLab Box 4.2.10 либо совместимая EVE-NG;
- SSH-доступ к `root` или другому пользователю с правами записи в `/opt/unetlab`;
- доступ к web-интерфейсу с Mac.

Подходят Intel/AMD-ПК с VMware Workstation, Proxmox/bare metal или сервер, где провайдер явно разрешает nested virtualization. Обычный VPS без `/dev/kvm` не подходит.

## Подготовка PNETLab Box

PNETLab распространяется как OVA. В настройках VM нужно пробросить аппаратную виртуализацию гостю. После первого запуска завершите начальную настройку PNETLab, узнайте IP и проверьте SSH.

Создайте локальную конфигурацию:

```bash
cp data.env.example data.env
chmod 600 data.env
```

Укажите в `data.env`:

- `PNETLAB_HOST` — IP или DNS PNETLab Box;
- `PNETLAB_SSH_USER` и `PNETLAB_SSH_PORT`;
- `PNETLAB_SSH_KEY` либо `PNETLAB_SSH_PASSWORD`;
- `VESR_USERNAME` и `VESR_PASSWORD` для скрипта сохранения конфигураций vESR;
- `VESR_IMAGE`, если подготовленный `hda.qcow2` уже находится в `images/`.

## Команды

`./lab remote-doctor` проверяет:

- целостность локального `.unl`;
- наличие интеграции vESR;
- SSH и web-интерфейс;
- x86_64, CPU-флаги и `/dev/kvm`;
- установку `/opt/unetlab`;
- наличие образа vESR.

`./lab remote-deploy` устанавливает:

- топологию в `/opt/unetlab/labs/Labs-IB/Networks-Labs.unl`;
- шаблоны vESR для AMD, Intel и legacy;
- скрипт импорта/экспорта конфигурации с параметрами из `data.env`;
- `hda.qcow2`, если задан `VESR_IMAGE`;
- корректные права через `unl_wrapper -a fixpermissions`.

`./lab remote-status` проверяет установленные файлы. `./lab remote-open` открывает web-интерфейс.

## Какие образы нужны топологии

Исходный архив содержит только XML-топологию и не содержит vendor-образов. Для запуска всех узлов нужны:

- Cisco IOL L3: `L3_ADVENTERPRISEK9_M_15.4_2T.bin`;
- Cisco IOL L2: `L2-ADVIPSERVICESK9-M-15.2-IRON-20170202.bin`;
- MikroTik: `mikrotik-6.49.1` и `mikrotik-6.39`;
- Linux QEMU: `linux-Debian-11-srv`;
- Eltex vESR: подготовленный `hda.qcow2` из лицензированного ISO.

VPCS входит в PNETLab. Остальные образы необходимо получить законным способом у производителей или из материалов курса. Репозиторий их не распространяет.

## Состав исходной топологии

- 103 узла;
- 46 Cisco IOL;
- 35 VPCS;
- 22 QEMU-узла (11 MikroTik и 11 Debian);
- 133 сети и 263 интерфейса.

## Источники

- [Требования PNETLab](https://pnetlab.com/pages/documentation?slug=hardware-requirements)
- [Установка и загрузка PNETLab](https://pnetlab.com/pages/download)
- [Неподдерживаемые платформы EVE-NG](https://www.eve-ng.net/index.php/not-supported-systems-or-hw/)
- [Интеграция Eltex vESR с EVE-NG](https://github.com/alekho/EVE-NG_vESR)
- [Исследование логики и таблица совместимости локального стенда](PNETLAB_COMPATIBILITY.md)
- [Видео: установка PNETLab на VMware Workstation](https://www.youtube.com/watch?v=VTEis9rLEto)
- [Видео: добавление Eltex в EVE-NG](https://www.youtube.com/watch?v=VT50BHPn96Y&t=246s)

## Бесплатные варианты

Полностью бесплатный и рабочий вариант — использовать имеющийся Intel/AMD-ПК: старый ноутбук, стационарный компьютер или вузовский сервер. PNETLab Box запускается там, а Mac подключается к нему по сети.

Если такого компьютера нет, иногда подходят стартовые trial-кредиты Google Cloud. Это временный вариант: аккаунту нужна доступная акция, а выбранная Compute Engine VM должна поддерживать nested virtualization. Постоянно бесплатные микро-VM и ARM-инстансы для этого стенда не подходят.
