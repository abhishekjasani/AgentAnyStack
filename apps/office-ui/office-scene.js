import { planOffice } from "./office-layout.mjs";
import * as THREE from "./vendor/three.module.min.js";

// Voxel office using locally vendored Three.js. Status always comes from the API.
const host = document.querySelector("#voxel-world");
const reducedMotion = matchMedia("(prefers-reduced-motion: reduce)");
let renderer;
try {
  renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true });
} catch (_) {
  host.hidden = true;
  document.querySelector(".world-navigation").hidden = true;
  document.querySelector("#world-fallback").hidden = false;
}
if (renderer) startOffice();

function startOffice() {
  let floorPage = 0,
    searchQuery = "",
    previousFilter = "";
  renderer.setPixelRatio(Math.min(devicePixelRatio, 2));
  renderer.shadowMap.enabled = true;
  renderer.shadowMap.type = THREE.PCFSoftShadowMap;
  renderer.shadowMap.autoUpdate = false;
  renderer.outputColorSpace = THREE.SRGBColorSpace;
  host.prepend(renderer.domElement);
  renderer.domElement.setAttribute("aria-hidden", "true");
  document.querySelector("#floor-map").classList.add("voxel-fallback");
  renderer.domElement.addEventListener("webglcontextlost", () => {
    host.hidden = true;
    document.querySelector(".world-navigation").hidden = true;
    document.querySelector(".floor-panel").classList.remove("world-expanded");
    document.querySelector("#world-expand").setAttribute("aria-pressed", "false");
    document.querySelector("#floor-map").classList.remove("voxel-fallback");
    document.querySelector("#world-fallback").hidden = false;
  });
  const scene = new THREE.Scene();
  const camera = new THREE.OrthographicCamera(-20, 20, 15, -15, 0.1, 180);
  const ambient = new THREE.HemisphereLight(0xcceeff, 0x567046, 2.6);
  scene.add(ambient);
  const sun = new THREE.DirectionalLight(0xffe6be, 4.2);
  sun.position.set(-14, 30, 18);
  sun.castShadow = true;
  sun.shadow.mapSize.set(2048, 2048);
  Object.assign(sun.shadow.camera, {
    left: -32,
    right: 32,
    top: 32,
    bottom: -32,
    far: 100,
  });
  sun.shadow.bias = -0.001;
  scene.add(sun);
  const fill = new THREE.DirectionalLight(0xa6c7ff, 1.4);
  fill.position.set(15, 10, -10);
  scene.add(fill);
  const world = new THREE.Group();
  scene.add(world);
  const geometry = new THREE.BoxGeometry(1, 1, 1);
  const materials = new Map();
  const material = (color, glow = false) => {
    const key = `${color}-${glow}`;
    if (!materials.has(key))
      materials.set(
        key,
        new THREE.MeshStandardMaterial({
          color,
          roughness: 0.85,
          ...(glow ? { emissive: color, emissiveIntensity: 0.7 } : {}),
        }),
      );
    return materials.get(key);
  };
  const box = (x, y, z, w, h, d, color, parent = world, glow = false) => {
    const mesh = new THREE.Mesh(geometry, material(color, glow));
    mesh.position.set(x, y + h / 2, z);
    mesh.scale.set(w, h, d);
    mesh.castShadow = true;
    mesh.receiveShadow = true;
    parent.add(mesh);
    return mesh;
  };
  let labels = [],
    actors = [],
    angle = 0.7,
    zoom = 1,
    mapDepth = 20,
    snapshot = null,
    signature = "";
  const overlay = host.querySelector(".world-labels");
  function label(text, x, y, z, action, id, type = "room") {
    const button = document.createElement("button");
    button.className = `world-label world-label-${type}`;
    button.textContent = text;
    button.title = text;
    button.dataset[action] = id;
    overlay.append(button);
    labels.push({ button, position: new THREE.Vector3(x, y, z) });
    return button;
  }
  function plant(x, z) {
    box(x, 0.1, z, 0.7, 0.65, 0.7, "#be9876");
    box(x, 0.75, z, 0.18, 0.75, 0.18, "#7a6747");
    box(x, 1.25, z, 1.15, 0.8, 0.95, "#547e4b");
    box(x - 0.2, 1.9, z, 0.8, 0.45, 0.75, "#729b59");
    box(x + 0.35, 1.1, z + 0.15, 0.65, 0.6, 0.7, "#628b4b");
  }
  function chair(x, z, color = "#59778a", rotation = 0) {
    const group = new THREE.Group();
    group.position.set(x, 0, z);
    group.rotation.y = rotation;
    world.add(group);
    box(0, 0.18, 0, 0.18, 0.6, 0.18, "#343f4b", group);
    box(0, 0.12, 0, 1, 0.1, 0.15, "#343f4b", group);
    box(0, 0.12, 0, 0.15, 0.1, 1, "#343f4b", group);
    box(0, 0.75, 0, 0.95, 0.18, 0.85, color, group);
    box(0, 0.85, 0.43, 0.95, 0.9, 0.16, color, group);
  }
  function character(x, z, index, working) {
    const group = new THREE.Group();
    group.position.set(x, 0, z);
    world.add(group);
    const shirt = ["#65c6b0", "#a58ce2", "#e5a461", "#6e9bdc", "#df8194"][
      index % 5
    ];
    const skin = ["#d6a77c", "#b78360", "#efc7a5", "#93694e"][index % 4];
    box(-0.22, 0.4, -0.2, 0.32, 0.5, 0.7, "#334258", group);
    box(0.22, 0.4, -0.2, 0.32, 0.5, 0.7, "#334258", group);
    box(0, 0.9, 0, 0.85, 0.7, 0.48, shirt, group);
    box(0, 1.64, 0, 0.62, 0.65, 0.62, skin, group);
    box(0, 2.15, 0.01, 0.68, 0.18, 0.67, "#473a37", group);
    box(0, 1.86, 0.28, 0.67, 0.4, 0.12, "#473a37", group);
    box(-0.15, 1.96, -0.32, 0.1, 0.09, 0.025, "#253641", group);
    box(0.15, 1.96, -0.32, 0.1, 0.09, 0.025, "#253641", group);
    const hands = [
      box(-0.55, 1.05, -0.33, 0.27, 0.25, 0.75, shirt, group),
      box(0.55, 1.05, -0.33, 0.27, 0.25, 0.75, shirt, group),
    ];
    box(-0.55, 1.05, -0.77, 0.25, 0.2, 0.23, skin, group);
    box(0.55, 1.05, -0.77, 0.25, 0.2, 0.23, skin, group);
    if (working) actors.push({ hands, seed: index });
  }
  function desk(x, z, agent, index) {
    box(x, 1.16, z, 2.6, 0.2, 1.4, "#cfb58b");
    for (const dx of [-1.05, 1.05])
      for (const dz of [-0.5, 0.5])
        box(x + dx, 0.1, z + dz, 0.12, 1.07, 0.12, "#5d6b73");
    box(x, 1.36, z - 0.27, 0.46, 0.07, 0.35, "#354655");
    box(x, 1.4, z - 0.3, 0.1, 0.4, 0.1, "#354655");
    box(x, 1.7, z - 0.3, 1.18, 0.75, 0.12, "#29394b");
    const active =
      agent.kind === "human"
        ? null
        : snapshot.active.find((r) => r.agent_id === agent.id);
    const waiting =
      agent.kind !== "human" &&
      snapshot.approvals.some((r) => r.agent_id === agent.id);
    box(
      x,
      1.77,
      z - 0.23,
      1.03,
      0.59,
      0.025,
      active ? "#64d9b6" : "#6998b1",
      world,
      !!active,
    );
    for (let i = 0; i < 3; i++)
      box(
        x - 0.12,
        1.86 + i * 0.12,
        z - 0.2,
        0.55 - (i % 2) * 0.2,
        0.025,
        0.025,
        "#c1ebdd",
      );
    box(x, 1.36, z + 0.36, 0.9, 0.05, 0.3, "#c4ccd0");
    box(x + 0.9, 1.36, z + 0.15, 0.23, 0.3, 0.23, "#f2e9d5");
    chair(x, z + 1.25);
    character(x, z + 1.05, index, !!active);
    const state =
      agent.kind === "human"
        ? agent.is_current
          ? "You · human"
          : "Human · listed"
        : active?.status || (waiting ? "Needs approval" : "Available");
    const button = label(
      `${agent.name} · ${state}`,
      x,
      3.15,
      z + 0.5,
      agent.kind === "human" ? "roomView" : "desk",
      agent.kind === "human" ? "people" : agent.id,
      "agent",
    );
    button.classList.toggle("agent-live", !!active);
    button.classList.toggle("agent-waiting", waiting);
    button.setAttribute("aria-label", `${agent.name} — ${state}`);
  }
  function table(x, z) {
    box(x, 1.15, z, 3.5, 0.22, 2.2, "#b59167");
    box(x - 1.1, 0.1, z, 0.25, 1.05, 1.4, "#586874");
    box(x + 1.1, 0.1, z, 0.25, 1.05, 1.4, "#586874");
    box(x, 1.38, z, 0.8, 0.03, 0.6, "#e9e6d7");
    for (const dx of [-1, 1]) {
      chair(x + dx, z + 1.65, "#9584b6");
      chair(x + dx, z - 1.65, "#9584b6", Math.PI);
    }
  }
  function rebuild(data) {
    snapshot = data;
    const filterKey = `${data.team}|${data.arrangement}`;
    if (filterKey !== previousFilter) {
      floorPage = 0;
      previousFilter = filterKey;
    }
    const plan = planOffice(data.agents, data.people, {
      team: data.team,
      arrangement: data.arrangement,
      query: searchQuery,
      page: floorPage,
    });
    floorPage = plan.page;
    document.querySelector("#world-page").textContent =
      `Floor ${plan.page + 1} / ${plan.pageCount} · ${plan.visible} of ${plan.total}`;
    document.querySelector("#world-prev").disabled = plan.page === 0;
    document.querySelector("#world-next").disabled =
      plan.page >= plan.pageCount - 1;
    const key = JSON.stringify([
      plan.rows,
      data.people,
      floorPage,
      searchQuery,
      data.active.map((r) => [r.agent_id, r.status]),
      data.approvals.map((r) => [r.id, r.agent_id]),
      data.arrangement,
      data.team,
    ]);
    if (signature === key) return;
    signature = key;
    const focusedLabel = document.activeElement?.closest(".world-label");
    const focusedAction = focusedLabel
      ? Object.entries(focusedLabel.dataset)[0]
      : null;
    world.clear();
    overlay.replaceChildren();
    labels = [];
    actors = [];
    const rows = plan.rows;
    const agents = rows.flatMap((row) => row.members);
    mapDepth = Math.max(20, rows.length * 4.2 + 12);
    // Floating block foundation with an exposed earth/stone edge.
    box(0, -1.3, 0, 26, 1.2, mapDepth + 2, "#445263");
    box(0, -0.35, 0, 26.3, 0.3, mapDepth + 2.3, "#748777");
    for (let x = -12; x <= 12; x++)
      for (let z = -mapDepth / 2; z < mapDepth / 2; z++) {
        const right = x > 4;
        const walkway = x >= 2 && x <= 4;
        const tone = walkway
          ? (x + Math.floor(z)) % 2
            ? "#bcc5c7"
            : "#c5ccce"
          : right
            ? "#c4b8a2"
            : (x + Math.floor(z)) % 3
              ? "#c1ad8e"
              : "#cbb99d";
        box(x, -0.05, z + 0.5, 0.98, 0.1, 0.98, tone);
      }
    const back = -mapDepth / 2;
    // Cutaway exterior walls, windows, and brick pillars.
    box(0, 0.05, back, 25.5, 0.85, 0.3, "#c0c5c0");
    for (let x = -12; x <= 12; x += 4) {
      box(x, 0.05, back, 0.48, 4.2, 0.48, "#d2d6c9");
      if (x < 12) {
        box(x + 2, 0.95, back, 3.45, 2.75, 0.1, "#94c4d1");
        box(x + 2, 2.25, back + 0.08, 3.5, 0.09, 0.1, "#e6e7d6");
        box(x + 2, 0.9, back + 0.08, 0.1, 2.8, 0.1, "#e6e7d6");
        box(x + 2, 3.75, back, 3.6, 0.24, 0.45, "#d7dcca");
      }
    }
    box(-12.5, 0.05, 0, 0.25, 0.55, mapDepth, "#c0c5b7");
    box(12.5, 0.05, 0, 0.25, 0.55, mapDepth, "#c0c5b7");
    // Main work studio with project/team islands.
    rows.forEach((row, ri) => {
      const z = back + 3 + ri * 4.2;
      box(
        -5.8,
        0.07,
        z + 0.5,
        12.1,
        0.035,
        3.8,
        ri % 2 ? "#788795" : "#78988d",
      );
      row.members.forEach((a, i) =>
        desk(
          -10 + i * 4.2,
          z,
          a,
          Math.max(
            0,
            [...data.agents, ...(data.people || [])].findIndex(
              (item) => item.id === a.id,
            ),
          ),
        ),
      );
      if (row.first)
        label(
          row.group.toUpperCase(),
          -6,
          0.4,
          z - 1.4,
          "roomView",
          "team",
          "zone",
        );
    });
    if (!agents.length)
      label(
        searchQuery ? "NO MATCHES · VIEW DIRECTORY" : "+ SEAT YOUR FIRST AGENT",
        -6,
        2,
        -2,
        searchQuery ? "roomView" : "createDesk",
        searchQuery ? "people" : "",
        "agent",
      );
    // Shared planning furniture is available even before more agents are seated.
    const hubZ = back + Math.max(1, rows.length) * 4.2 + 2.8;
    box(-6, 0.08, hubZ, 8, 0.035, 4.4, "#a4aa8b");
    table(-6, hubZ);
    for (const x of [-7, -5]) {
      box(x, 1.4, hubZ, 0.7, 0.035, 0.48, "#647a82");
      box(x, 1.44, hubZ - 0.2, 0.7, 0.43, 0.06, "#344d5c");
      box(x, 1.48, hubZ - 0.16, 0.59, 0.31, 0.02, "#a3c5bd");
    }
    box(-10.7, 0.1, hubZ, 0.14, 1.1, 0.14, "#667878");
    box(-10.7, 1.2, hubZ, 0.15, 1.6, 2.6, "#e1dfc9");
    for (let i = 0; i < 4; i++)
      box(
        -10.59,
        1.5 + (i % 2) * 0.55,
        hubZ - 0.6 + Math.floor(i / 2) * 0.75,
        0.03,
        0.35,
        0.4,
        ["#e2bd7e", "#85b3a1"][i % 2],
      );
    label("PROJECT HUB", -6, 3, hubZ, "roomView", "analytics");
    // Right wing: knowledge library, review room, machine room.
    for (const z of [back + 6, back + 12]) {
      box(8.5, 0.05, z, 7.7, 0.7, 0.2, "#bcc2b7");
      box(5, 0.05, z, 0.3, 2.6, 0.3, "#cdd2c6");
      box(11.9, 0.05, z, 0.3, 2.6, 0.3, "#cdd2c6");
    }
    for (const x of [6.2, 8.4, 10.6]) {
      box(x, 0.1, back + 0.8, 1.8, 2.9, 0.7, "#826849");
      for (let shelf = 0; shelf < 3; shelf++) {
        box(x, 0.25 + shelf * 0.85, back + 1.23, 1.85, 0.12, 0.95, "#c8a271");
        for (let b = 0; b < 6; b++)
          box(
            x - 0.7 + b * 0.27,
            0.38 + shelf * 0.85,
            back + 1.17,
            0.19,
            0.45 + (b % 3) * 0.08,
            0.38,
            ["#a1bfa2", "#b993ba", "#d4b16e", "#759eaf"][b % 4],
          );
      }
    }
    box(8, 0.08, back + 4, 4.5, 0.04, 2.2, "#9baf8e");
    box(8, 0.25, back + 4, 2, 0.5, 0.8, "#c0b18d");
    plant(11, back + 4.3);
    label("LIBRARY", 8.6, 3.6, back + 1.7, "roomView", "memory");
    box(8.5, 0.07, back + 9, 6.5, 0.04, 5, "#9f91ac");
    table(8.5, back + 9);
    box(12, 1.1, back + 8.5, 0.08, 1.5, 2.6, "#edeade");
    for (let i = 0; i < 3; i++)
      box(
        11.93,
        1.4 + i * 0.35,
        back + 8.5,
        0.06,
        0.12,
        1.7 - i * 0.3,
        "#85aa98",
      );
    label(
      `REVIEW ROOM${data.approvals.length ? " · " + data.approvals.length : ""}`,
      8.5,
      3.3,
      back + 9,
      "roomView",
      "approvals",
    );
    for (const x of [6.2, 8.4, 10.6]) {
      box(x, 0.12, back + 14.3, 1.3, 2.4, 1.1, "#354555");
      for (let i = 0; i < 5; i++) {
        box(x, 0.28 + i * 0.43, back + 14.88, 1.1, 0.31, 0.04, "#536578");
        box(
          x + 0.37,
          0.4 + i * 0.43,
          back + 14.92,
          0.09,
          0.08,
          0.03,
          "#97dca8",
          world,
          true,
        );
        box(
          x - 0.18,
          0.4 + i * 0.43,
          back + 14.92,
          0.42,
          0.04,
          0.03,
          "#263641",
        );
      }
    }
    label("SERVER ROOM", 8.5, 3.2, back + 14.3, "roomView", "stacks");
    // Front lounge, reception counter, coffee machine, and trees.
    const front = mapDepth / 2 - 2;
    box(-7, 0.08, front - 0.4, 9, 0.035, 3.6, "#abb299");
    box(-9.5, 0.2, front, 3.5, 0.5, 1.05, "#ce9367");
    box(-9.5, 0.65, front + 0.4, 3.5, 0.7, 0.25, "#dfa776");
    for (const x of [-11.1, -7.9])
      box(x, 0.2, front, 0.3, 0.95, 1.2, "#c08964");
    box(-6.5, 0.25, front - 0.3, 1.8, 0.65, 1.2, "#b39872");
    box(-6.5, 0.93, front - 0.3, 0.7, 0.02, 0.5, "#ede2c8");
    box(-2.9, 0.1, front, 2.2, 1.15, 1.1, "#c4a277");
    box(-2.9, 1.25, front, 2.4, 0.12, 1.3, "#e3cfaa");
    box(-2.9, 1.37, front, 0.65, 0.72, 0.65, "#48515a");
    box(-2.9, 1.55, front + 0.34, 0.3, 0.36, 0.04, "#b9c6ca");
    label("RECEPTION", -6.4, 2.8, front, "officeChat", "");
    plant(-11, back + 1);
    plant(1.1, back + 1);
    plant(1, front);
    plant(11.5, front);
    // Lit pathway is environmental decoration, not a fabricated activity signal.
    for (let z = back + 1; z < front + 1; z += 2)
      box(3, 0.07, z, 0.16, 0.03, 0.7, "#d5e0b2", world, true);
    box(3, -0.65, mapDepth / 2 + 1.8, 4, 0.3, 1, "#778c85");
    box(3, -0.95, mapDepth / 2 + 2.6, 4.4, 0.3, 1, "#637871");
    if (focusedAction)
      labels
        .find(
          (item) => item.button.dataset[focusedAction[0]] === focusedAction[1],
        )
        ?.button.focus({ preventScroll: true });
    renderer.shadowMap.needsUpdate = true;
    resize();
  }
  function resize() {
    const { width, height } = host.getBoundingClientRect();
    if (!width || !height) return;
    renderer.setSize(width, height, false);
    const aspect = width / height;
    const span = Math.max(17, mapDepth * 0.72, 20 / aspect) / zoom;
    camera.left = -span * aspect;
    camera.right = span * aspect;
    camera.top = span;
    camera.bottom = -span;
    camera.updateProjectionMatrix();
    render();
  }
  function render(time = 0) {
    camera.position.set(Math.sin(angle) * 35, 31, Math.cos(angle) * 35);
    camera.lookAt(0, 0, 0);
    camera.updateMatrixWorld();
    if (!reducedMotion.matches)
      actors.forEach(({ hands, seed }) =>
        hands.forEach((hand, i) => {
          hand.position.y =
            1.175 + Math.sin(time * 0.013 + seed + i * Math.PI) * 0.05;
        }),
      );
    renderer.render(scene, camera);
    const width = host.clientWidth,
      height = host.clientHeight;
    // Lay labels out in two passes to avoid alternating DOM reads/writes.
    const projected = labels.map(({button, position}) => {
      const p = position.clone().project(camera);
      return {button, p, w: button.offsetWidth || 130, h: button.offsetHeight || 26};
    });
    const occupied = [];
    for (const {button, p, w, h} of projected) {
      const hidden = Math.abs(p.x) > .98 || Math.abs(p.y) > .97;
      button.hidden = hidden;
      if (hidden) continue;
      const x = Math.max(w / 2 + 6, Math.min(width - w / 2 - 6, (p.x + 1) * width / 2));
      const originalY = (1 - p.y) * height / 2;
      let y = originalY;
      const overlaps = () => occupied.some(r => x - w/2 < r.right + 4 && x + w/2 > r.left - 4 && y - h < r.bottom + 4 && y > r.top - 4);
      for (let attempt = 0; overlaps() && attempt < 14; attempt++) {
        const offset = Math.ceil((attempt + 1) / 2) * (h + 6);
        y = Math.max(80 + h, Math.min(height - 80, originalY + (attempt % 2 ? offset : -offset)));
      }
      occupied.push({left:x-w/2,right:x+w/2,top:y-h,bottom:y});
      button.style.left = `${x}px`;
      button.style.top = `${y}px`;
    }

  }
  let drag = null;
  renderer.domElement.addEventListener("pointerdown", (event) => {
    drag = { x: event.clientX, angle };
    renderer.domElement.setPointerCapture(event.pointerId);
  });
  renderer.domElement.addEventListener("pointermove", (event) => {
    if (!drag) return;
    angle = Math.max(
      -1.15,
      Math.min(1.15, drag.angle + (event.clientX - drag.x) * 0.005),
    );
    render();
  });
  renderer.domElement.addEventListener("pointerup", () => {
    drag = null;
  });
  renderer.domElement.addEventListener("pointercancel", () => {
    drag = null;
  });
  host.querySelectorAll("[data-camera]").forEach((button) =>
    button.addEventListener("click", () => {
      const action = button.dataset.camera;
      if (action === "left") angle = Math.max(-1.15, angle - 0.25);
      if (action === "right") angle = Math.min(1.15, angle + 0.25);
      if (action === "in") zoom = Math.min(1.8, zoom + 0.15);
      if (action === "out") zoom = Math.max(0.7, zoom - 0.15);
      if (action === "reset") {
        angle = 0.7;
        zoom = 1;
      }
      resize();
    }),
  );
  document.querySelector("#world-expand").addEventListener("click", () => {
    const expanded = document
      .querySelector(".floor-panel")
      .classList.toggle("world-expanded");
    document
      .querySelector("#world-expand")
      .setAttribute("aria-pressed", String(expanded));
    resize();
  });
  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape" && document.querySelector(".world-expanded")) {
      document.querySelector(".floor-panel").classList.remove("world-expanded");
      document
        .querySelector("#world-expand")
        .setAttribute("aria-pressed", "false");
      resize();
      document.querySelector("#world-expand").focus();
    }
  });
  document.querySelector("#world-search").addEventListener("input", (event) => {
    searchQuery = event.target.value;
    floorPage = 0;
    if (snapshot) rebuild(snapshot);
  });
  document.querySelector("#world-prev").addEventListener("click", () => {
    floorPage--;
    if (snapshot) rebuild(snapshot);
  });
  document.querySelector("#world-next").addEventListener("click", () => {
    floorPage++;
    if (snapshot) rebuild(snapshot);
  });
  new ResizeObserver(resize).observe(host);
  document.addEventListener("office-snapshot", (event) =>
    rebuild(event.detail),
  );
  if (window.officeSceneSnapshot) rebuild(window.officeSceneSnapshot);
  let lastFrame = 0;
  renderer.setAnimationLoop((time) => {
    if (
      document.hidden ||
      document.querySelector("#view-floor").hidden ||
      !actors.length ||
      reducedMotion.matches ||
      time - lastFrame < 65
    )
      return;
    lastFrame = time;
    render(time);
  });
}
