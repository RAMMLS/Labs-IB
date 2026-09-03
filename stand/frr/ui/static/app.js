const canvas = document.getElementById("lab-canvas");
const nodesLayer = document.getElementById("nodes-layer");
const linksLayer = document.getElementById("links-layer");
const modeHint = document.getElementById("mode-hint");
let topology = {title: "Новая лабораторная", nodes: [], links: []};
let linkMode = false;
let firstLinkNode = null;
let pendingLink = null;
let menuNode = null;
let selectedNode = null;
let dragging = null;
let dragMoved = false;
let toastTimer = null;
let consoleSession = null;
let consoleHistory = [];
let consoleHistoryIndex = 0;
let startupSelection = null;

const routerIcon = `
  <svg viewBox="0 0 90 64" aria-hidden="true">
    <ellipse class="router-body" cx="45" cy="32" rx="38" ry="20"/>
    <path class="router-mark" d="M24 27h15l-5-5m5 5-5 5M66 37H51l5-5m-5 5 5 5M41 16v11l-5-5m5 5 5-5M49 48V37l-5 5m5-5 5 5" fill="none"/>
  </svg>`;
const pcIcon = `
  <svg viewBox="0 0 90 64" aria-hidden="true">
    <rect class="pc-case" x="16" y="5" width="58" height="41" rx="3"/>
    <rect class="pc-screen" x="21" y="10" width="48" height="30" rx="1"/>
    <rect class="pc-base" x="40" y="46" width="10" height="8"/>
    <path class="pc-base" d="M27 54h36l7 6H20z"/>
  </svg>`;

async function api(path, options = {}) {
  const response = await fetch(path, {
    ...options,
    headers: {"Content-Type": "application/json", ...(options.headers || {})},
  });
  const payload = await response.json();
  if (!response.ok || payload.ok === false) throw new Error(payload.error || "Ошибка стенда");
  return payload;
}

function toast(message, error = false) {
  const element = document.getElementById("toast");
  element.textContent = message;
  element.classList.toggle("error", error);
  element.classList.add("show");
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => element.classList.remove("show"), 3200);
}

function nodeById(id) {
  return topology.nodes.find(node => node.id === id);
}

function svgElement(name, attributes = {}) {
  const element = document.createElementNS("http://www.w3.org/2000/svg", name);
  for (const [key, value] of Object.entries(attributes)) element.setAttribute(key, value);
  return element;
}

function addInterfaceLabel(x, y, text) {
  const width = Math.max(48, text.length * 6 + 12);
  const group = svgElement("g");
  group.appendChild(svgElement("rect", {x: x - width / 2, y: y - 9, width, height: 18, class: "link-interface"}));
  const label = svgElement("text", {x, y, class: "link-label"});
  label.textContent = text;
  group.appendChild(label);
  linksLayer.appendChild(group);
}

function renderLinks() {
  linksLayer.innerHTML = "";
  for (const link of topology.links) {
    const a = nodeById(link.a);
    const b = nodeById(link.b);
    if (!a || !b) continue;
    const running = a.running && b.running;
    linksLayer.appendChild(svgElement("line", {
      x1: a.x, y1: a.y, x2: b.x, y2: b.y,
      class: `topology-link ${running ? "running" : ""}`,
    }));
    const hit = svgElement("line", {x1: a.x, y1: a.y, x2: b.x, y2: b.y, class: "topology-link-hit"});
    hit.addEventListener("dblclick", async event => {
      event.stopPropagation();
      if (!confirm(`Удалить кабель ${a.name} ${link.a_if} — ${b.name} ${link.b_if}?`)) return;
      try {
        await api(`/api/links/${link.id}`, {method: "DELETE"});
        toast("Кабель удалён");
        await refresh();
      } catch (error) { toast(error.message, true); }
    });
    linksLayer.appendChild(hit);
    addInterfaceLabel(a.x + (b.x - a.x) * 0.22, a.y + (b.y - a.y) * 0.22 - 12, link.a_if);
    addInterfaceLabel(a.x + (b.x - a.x) * 0.78, a.y + (b.y - a.y) * 0.78 - 12, link.b_if);
  }
}

function renderNodes() {
  nodesLayer.innerHTML = "";
  for (const node of topology.nodes) {
    const element = document.createElement("div");
    element.className = `network-node ${node.running ? "running" : ""} ${firstLinkNode === node.id ? "link-first" : ""}`;
    element.dataset.nodeId = node.id;
    element.style.left = `${node.x}px`;
    element.style.top = `${node.y}px`;
    element.innerHTML = `
      <div class="quick-controls">
        <button data-quick="${node.running ? "console" : "start"}" title="${node.running ? "Веб-консоль" : "Запустить"}">${node.running ? "›_" : "▶"}</button>
        <button data-quick="connect" title="Соединить">⌁</button>
      </div>
      <div class="device-icon">${node.type === "router" ? routerIcon : pcIcon}</div>`;
    const label = document.createElement("div");
    label.className = "node-name";
    label.innerHTML = `<i class="state-dot"></i><span></span>`;
    label.querySelector("span").textContent = node.name;
    element.appendChild(label);
    element.title = `${node.name} · ${node.image}\n${node.ethernet} сетевых портов · ${node.cpu} процессорных ядер · ${node.ram} МБ ОЗУ`;
    element.addEventListener("click", event => onNodeClick(event, node));
    element.addEventListener("contextmenu", event => openNodeMenu(event, node.id));
    element.addEventListener("pointerdown", event => beginDrag(event, node, element));
    element.querySelectorAll("[data-quick]").forEach(button => {
      button.addEventListener("pointerdown", event => event.stopPropagation());
      button.addEventListener("click", async event => {
        event.stopPropagation();
        if (button.dataset.quick === "connect") {
          linkMode = true;
          firstLinkNode = node.id;
          document.getElementById("add-link").classList.add("active");
          modeHint.textContent = `Выбери второй узел для связи с ${node.name}`;
          renderNodes();
        } else if (button.dataset.quick === "console") {
          openConsole(node.id);
        } else {
          await actionForNode(node.id, "start");
        }
      });
    });
    nodesLayer.appendChild(element);
  }
}

function render() {
  document.getElementById("lab-title").textContent = topology.title || "Новая лабораторная";
  document.getElementById("router-count").textContent = topology.nodes.filter(node => node.type === "router").length;
  document.getElementById("pc-count").textContent = topology.nodes.filter(node => node.type === "pc").length;
  document.getElementById("link-count").textContent = topology.links.length;
  document.getElementById("running-count").textContent = topology.nodes.filter(node => node.running).length;
  document.getElementById("empty-state").hidden = topology.nodes.length > 0;
  renderLinks();
  renderNodes();
}

async function refresh() {
  if (dragging) return;
  try {
    topology = await api("/api/topology");
    render();
    document.getElementById("engine-dot").classList.remove("offline");
  } catch (error) {
    document.getElementById("engine-dot").classList.add("offline");
    toast(error.message, true);
  }
}

function openModal(id) {
  const modal = document.getElementById(id);
  modal.classList.add("open");
  modal.setAttribute("aria-hidden", "false");
}

function closeModal(id) {
  const modal = document.getElementById(id);
  modal.classList.remove("open");
  modal.setAttribute("aria-hidden", "true");
}

function suggestedName(type) {
  const base = type === "router" ? "vESR" : "PC";
  let number = 1;
  const names = new Set(topology.nodes.map(node => node.name));
  while (names.has(`${base}${number}`)) number += 1;
  return `${base}${number}`;
}

function syncTemplateFields() {
  const type = document.getElementById("node-template").value;
  document.getElementById("node-name").value = suggestedName(type);
  document.getElementById("node-image").value = type === "router" ? "FRRouting 10.7.1 / ARM64" : "Alpine Linux 3.22 / ARM64";
  document.getElementById("node-ram").value = type === "router" ? 512 : 128;
  document.getElementById("node-ethernet").value = type === "router" ? 4 : 1;
}

function showAddModal() {
  syncTemplateFields();
  openModal("add-modal");
  setTimeout(() => document.getElementById("node-name").select(), 50);
}

function nextFreePosition(scroll) {
  const originX = Math.max(170, scroll.scrollLeft + 170);
  const originY = Math.max(150, scroll.scrollTop + 150);
  for (let slot = 0; slot < 48; slot += 1) {
    const x = originX + (slot % 6) * 185;
    const y = originY + Math.floor(slot / 6) * 155;
    const occupied = topology.nodes.some(node => Math.abs(node.x - x) < 145 && Math.abs(node.y - y) < 115);
    if (!occupied) return {x, y};
  }
  return {x: originX + 40, y: originY + 40};
}

async function addNode(event) {
  event.preventDefault();
  const form = new FormData(event.currentTarget);
  const scroll = document.getElementById("canvas-scroll");
  const payload = Object.fromEntries(form.entries());
  const position = nextFreePosition(scroll);
  payload.x = position.x;
  payload.y = position.y;
  try {
    const response = await api("/api/nodes", {method: "POST", body: JSON.stringify(payload)});
    closeModal("add-modal");
    toast(`Создано узлов: ${response.result.length}. Они выключены.`);
    await refresh();
  } catch (error) { toast(error.message, true); }
}

function toggleLinkMode(force) {
  linkMode = force === undefined ? !linkMode : force;
  firstLinkNode = null;
  document.getElementById("add-link").classList.toggle("active", linkMode);
  modeHint.textContent = linkMode ? "Выбери первый узел" : "Перетаскивай устройства мышью";
  renderNodes();
}

function availablePorts(node) {
  return node.interfaces.filter(item => !item.used);
}

function showLinkDialog(a, b) {
  const aPorts = availablePorts(a);
  const bPorts = availablePorts(b);
  if (!aPorts.length || !bPorts.length) {
    toast("У одного из узлов не осталось свободных сетевых портов", true);
    toggleLinkMode(false);
    return;
  }
  pendingLink = {a: a.id, b: b.id};
  document.getElementById("link-title").textContent = `СОЕДИНЕНИЕ: ${a.name} — ${b.name}`;
  document.getElementById("link-a-name").textContent = a.name;
  document.getElementById("link-b-name").textContent = b.name;
  for (const [id, ports] of [["link-a-interface", aPorts], ["link-b-interface", bPorts]]) {
    const select = document.getElementById(id);
    select.innerHTML = "";
    for (const port of ports) {
      const option = document.createElement("option");
      option.value = port.name;
      option.textContent = port.name;
      select.appendChild(option);
    }
  }
  openModal("link-modal");
}

async function onNodeClick(event, node) {
  event.stopPropagation();
  if (dragMoved) { dragMoved = false; return; }
  if (!linkMode) {
    if (node.running) openConsole(node.id);
    else toast("Узел выключен. Запусти его через ▶ или правый клик.");
    return;
  }
  if (!firstLinkNode) {
    firstLinkNode = node.id;
    modeHint.textContent = `Теперь выбери второй узел для связи с ${node.name}`;
    renderNodes();
    return;
  }
  if (firstLinkNode === node.id) {
    firstLinkNode = null;
    modeHint.textContent = "Выбери первый узел";
    renderNodes();
    return;
  }
  showLinkDialog(nodeById(firstLinkNode), node);
}

async function addLink(event) {
  event.preventDefault();
  if (!pendingLink) return;
  try {
    await api("/api/links", {
      method: "POST",
      body: JSON.stringify({
        ...pendingLink,
        a_if: document.getElementById("link-a-interface").value,
        b_if: document.getElementById("link-b-interface").value,
      }),
    });
    closeModal("link-modal");
    pendingLink = null;
    toggleLinkMode(false);
    toast("Кабель создан на выбранных интерфейсах");
    await refresh();
  } catch (error) { toast(error.message, true); }
}

function beginDrag(event, node, element) {
  if (event.button !== 0 || linkMode) return;
  event.preventDefault();
  dragMoved = false;
  const rect = canvas.getBoundingClientRect();
  dragging = {node, element, startX: event.clientX, startY: event.clientY, dx: event.clientX - rect.left - node.x, dy: event.clientY - rect.top - node.y};
  element.setPointerCapture(event.pointerId);
  const move = moveEvent => {
    if (!dragging) return;
    if (Math.hypot(moveEvent.clientX - dragging.startX, moveEvent.clientY - dragging.startY) > 4) dragMoved = true;
    const canvasRect = canvas.getBoundingClientRect();
    node.x = Math.max(60, Math.min(1840, moveEvent.clientX - canvasRect.left - dragging.dx));
    node.y = Math.max(55, Math.min(1070, moveEvent.clientY - canvasRect.top - dragging.dy));
    element.style.left = `${node.x}px`;
    element.style.top = `${node.y}px`;
    renderLinks();
  };
  const finish = async () => {
    if (!dragging) return;
    element.removeEventListener("pointermove", move);
    element.removeEventListener("pointerup", finish);
    element.removeEventListener("pointercancel", finish);
    dragging = null;
    try {
      await api(`/api/nodes/${node.id}`, {method: "PATCH", body: JSON.stringify({x: Math.round(node.x), y: Math.round(node.y)})});
    } catch (error) { toast(error.message, true); }
  };
  element.addEventListener("pointermove", move);
  element.addEventListener("pointerup", finish);
  element.addEventListener("pointercancel", finish);
}

function openNodeMenu(event, nodeId) {
  event.preventDefault();
  menuNode = nodeId;
  const node = nodeById(nodeId);
  document.getElementById("node-menu-title").textContent = `${node.name} (${node.id})`;
  const menu = document.getElementById("node-menu");
  menu.style.left = `${Math.min(event.clientX, innerWidth - 210)}px`;
  menu.style.top = `${Math.min(event.clientY, innerHeight - 330)}px`;
  menu.classList.add("open");
}

function closeNodeMenu() {
  document.getElementById("node-menu").classList.remove("open");
}

async function actionForNode(nodeId, action) {
  try {
    await api("/api/actions", {method: "POST", body: JSON.stringify({action, node: nodeId})});
    const messages = {start: "Узел запущен", stop: "Узел остановлен", restart: "Узел перезагружен", wipe: "Узел сброшен и выключен", export: "Стартовая конфигурация сохранена"};
    toast(messages[action] || "Готово");
    await refresh();
  } catch (error) { toast(error.message, true); }
}

function showEdit(node) {
  document.getElementById("edit-id").value = node.id;
  document.getElementById("edit-name").value = node.name;
  document.getElementById("edit-description").value = node.description || "";
  document.getElementById("edit-cpu").value = node.cpu;
  document.getElementById("edit-ram").value = node.ram;
  document.getElementById("edit-ethernet").value = node.ethernet;
  openModal("edit-modal");
}

async function saveEdit(event) {
  event.preventDefault();
  const id = document.getElementById("edit-id").value;
  const payload = {
    name: document.getElementById("edit-name").value,
    description: document.getElementById("edit-description").value,
    cpu: document.getElementById("edit-cpu").value,
    ram: document.getElementById("edit-ram").value,
    ethernet: document.getElementById("edit-ethernet").value,
  };
  try {
    await api(`/api/nodes/${id}`, {method: "PATCH", body: JSON.stringify(payload)});
    closeModal("edit-modal");
    toast("Параметры узла сохранены");
    await refresh();
  } catch (error) { toast(error.message, true); }
}

function showCapture(node) {
  const ports = node.interfaces.filter(item => item.used);
  if (!node.running || !ports.length) {
    toast("Для захвата запусти узел и подключи кабель", true);
    return;
  }
  selectedNode = node.id;
  const select = document.getElementById("capture-interface");
  select.innerHTML = "";
  for (const port of ports) {
    const option = document.createElement("option");
    option.value = port.name;
    option.textContent = `${port.name}${port.actual ? ` (${port.actual})` : ""}`;
    select.appendChild(option);
  }
  document.getElementById("capture-output").textContent = "Выберите интерфейс и нажмите «Начать захват».";
  openModal("capture-modal");
}

async function runCapture(event) {
  event.preventDefault();
  const output = document.getElementById("capture-output");
  output.textContent = "Слушаю интерфейс…";
  try {
    const response = await api("/api/capture", {method: "POST", body: JSON.stringify({node: selectedNode, interface: document.getElementById("capture-interface").value})});
    output.textContent = response.result.output;
  } catch (error) { output.textContent = `Ошибка: ${error.message}`; }
}

async function nodeAction(action) {
  const node = nodeById(menuNode);
  closeNodeMenu();
  if (!node) return;
  if (action === "console") return openConsole(node.id);
  if (action === "edit") return showEdit(node);
  if (action === "capture") return showCapture(node);
  if (action === "delete") {
    if (!confirm(`Удалить узел ${node.name}, его кабели и сохранённую конфигурацию?`)) return;
    try {
      await api(`/api/nodes/${node.id}`, {method: "DELETE"});
      toast("Узел удалён");
      await refresh();
    } catch (error) { toast(error.message, true); }
    return;
  }
  if (action === "wipe" && !confirm(`Сброс удалит рабочее состояние узла ${node.name}. Сохранённая стартовая конфигурация останется. Продолжить?`)) return;
  await actionForNode(node.id, action);
  if (action === "export") window.location.href = `/api/nodes/${node.id}/config`;
}

function appendConsole(text) {
  if (!text) return;
  const output = document.getElementById("console-output");
  output.textContent += (output.textContent ? "\n" : "") + text;
  output.scrollTop = output.scrollHeight;
}

async function beginConsoleSession() {
  const node = nodeById(selectedNode);
  if (!node) return;
  const mode = document.getElementById("console-mode").value;
  try {
    const response = await api("/api/console/session", {method: "POST", body: JSON.stringify({node: node.id, mode})});
    consoleSession = response.result.session;
    document.getElementById("console-output").textContent = response.result.output;
    document.getElementById("console-prompt").textContent = response.result.prompt;
  } catch (error) {
    consoleSession = null;
    document.getElementById("console-output").textContent = `Ошибка: ${error.message}`;
  }
}

async function openConsole(nodeId) {
  const node = nodeById(nodeId);
  if (!node) return;
  if (!node.running) {
    toast("Сначала запусти ноду", true);
    return;
  }
  selectedNode = nodeId;
  document.getElementById("console-title").textContent = `Веб-консоль — ${node.name}`;
  document.getElementById("console-status").textContent = `${node.image} · работает`;
  const mode = document.getElementById("console-mode");
  mode.querySelector('option[value="frr"]').disabled = node.type !== "router";
  mode.querySelector('option[value="vpc"]').disabled = node.type !== "pc";
  mode.value = node.type === "router" ? "frr" : "vpc";
  const used = node.interfaces.filter(item => item.used);
  document.getElementById("interface-list").textContent = used.length
    ? used.map(item => `${item.name}→${item.actual || "ожидание"}`).join(" · ")
    : "Интерфейсы: кабели не подключены";
  document.getElementById("console-output").textContent = "";
  document.getElementById("console-input").value = "";
  openModal("console-modal");
  await beginConsoleSession();
  document.getElementById("console-input").focus();
}

async function runConsoleCommand(event) {
  event.preventDefault();
  const input = document.getElementById("console-input");
  const command = input.value.trim();
  if (!command || !consoleSession) return;
  consoleHistory.push(command);
  consoleHistoryIndex = consoleHistory.length;
  appendConsole(`${document.getElementById("console-prompt").textContent} ${command}`);
  input.value = "";
  input.disabled = true;
  try {
    const response = await api("/api/console", {method: "POST", body: JSON.stringify({session: consoleSession, command})});
    appendConsole(response.result.output);
    document.getElementById("console-prompt").textContent = response.result.prompt;
    await refresh();
  } catch (error) { appendConsole(`% Ошибка: ${error.message}`); }
  input.disabled = false;
  input.focus();
}

async function openStartupConfigs() {
  openModal("startup-modal");
  const list = document.getElementById("startup-list");
  list.innerHTML = '<div class="loading">Загрузка…</div>';
  try {
    const response = await api("/api/startup-configs");
    list.innerHTML = "";
    if (!response.result.length) list.innerHTML = '<div class="loading">Сначала добавьте узлы</div>';
    for (const config of response.result) {
      const button = document.createElement("button");
      button.className = "startup-item";
      button.innerHTML = `<b></b><span>${config.content ? "сохранена" : "не сохранена"} · ${config.enabled ? "включена" : "отключена"}</span>`;
      button.querySelector("b").textContent = config.name;
      button.addEventListener("click", () => selectStartup(config, button));
      list.appendChild(button);
    }
  } catch (error) { list.textContent = error.message; }
}

function selectStartup(config, button) {
  startupSelection = config.node;
  document.querySelectorAll(".startup-item").forEach(item => item.classList.toggle("selected", item === button));
  document.getElementById("startup-name").textContent = config.name;
  document.getElementById("startup-enabled").checked = config.enabled;
  document.getElementById("startup-content").value = config.content;
  document.getElementById("startup-content").disabled = false;
  document.getElementById("startup-save").disabled = false;
  const download = document.getElementById("startup-download");
  download.classList.toggle("disabled", !config.content);
  download.href = config.content ? `/api/nodes/${config.node}/config` : "";
}

async function saveStartup() {
  if (!startupSelection) return;
  try {
    await api(`/api/startup-configs/${startupSelection}`, {
      method: "PATCH",
      body: JSON.stringify({
        content: document.getElementById("startup-content").value,
        enabled: document.getElementById("startup-enabled").checked,
      }),
    });
    toast("Стартовая конфигурация сохранена");
    await openStartupConfigs();
  } catch (error) { toast(error.message, true); }
}

async function allAction(action) {
  try {
    await api("/api/actions", {method: "POST", body: JSON.stringify({action})});
    toast({start: "Все узлы запущены", stop: "Все узлы остановлены", export: "Конфигурации запущенных узлов сохранены"}[action]);
    await refresh();
  } catch (error) { toast(error.message, true); }
}

document.getElementById("add-node").addEventListener("click", showAddModal);
document.getElementById("empty-add").addEventListener("click", showAddModal);
document.getElementById("add-link").addEventListener("click", () => toggleLinkMode());
document.getElementById("startup-configs").addEventListener("click", openStartupConfigs);
document.getElementById("start-all").addEventListener("click", () => allAction("start"));
document.getElementById("stop-all").addEventListener("click", () => allAction("stop"));
document.getElementById("export-all").addEventListener("click", () => allAction("export"));
document.getElementById("refresh").addEventListener("click", refresh);
document.getElementById("node-template").addEventListener("change", syncTemplateFields);
document.getElementById("add-form").addEventListener("submit", addNode);
document.getElementById("link-form").addEventListener("submit", addLink);
document.getElementById("edit-form").addEventListener("submit", saveEdit);
document.getElementById("capture-form").addEventListener("submit", runCapture);
document.getElementById("console-form").addEventListener("submit", runConsoleCommand);
document.getElementById("console-mode").addEventListener("change", beginConsoleSession);
document.getElementById("console-clear").addEventListener("click", () => { document.getElementById("console-output").textContent = ""; });
document.getElementById("startup-save").addEventListener("click", saveStartup);
document.querySelectorAll("[data-close]").forEach(button => button.addEventListener("click", () => closeModal(button.dataset.close)));
document.querySelectorAll("[data-node-action]").forEach(button => button.addEventListener("click", () => nodeAction(button.dataset.nodeAction)));
canvas.addEventListener("click", () => { if (!linkMode) closeNodeMenu(); });
document.addEventListener("click", event => { if (!document.getElementById("node-menu").contains(event.target)) closeNodeMenu(); });
document.getElementById("console-input").addEventListener("keydown", event => {
  if (event.key === "ArrowUp" && consoleHistory.length) {
    event.preventDefault();
    consoleHistoryIndex = Math.max(0, consoleHistoryIndex - 1);
    event.currentTarget.value = consoleHistory[consoleHistoryIndex];
  }
  if (event.key === "ArrowDown" && consoleHistory.length) {
    event.preventDefault();
    consoleHistoryIndex = Math.min(consoleHistory.length, consoleHistoryIndex + 1);
    event.currentTarget.value = consoleHistory[consoleHistoryIndex] || "";
  }
});
document.addEventListener("keydown", event => {
  if (event.key !== "Escape") return;
  ["add-modal", "link-modal", "edit-modal", "console-modal", "startup-modal", "capture-modal"].forEach(closeModal);
  closeNodeMenu();
  toggleLinkMode(false);
});

refresh();
setInterval(refresh, 3000);
