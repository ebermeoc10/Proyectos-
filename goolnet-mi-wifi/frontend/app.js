// Mi WiFi Goolnet - PWA
const API = ""; // mismo origen que sirve el backend
let token = localStorage.getItem("goolnet_token") || null;

const $ = (s) => document.querySelector(s);
const show = (id) => { $("#view-login").classList.add("hidden"); $("#view-panel").classList.add("hidden"); $(id).classList.remove("hidden"); };

function toast(msg){
  const t = $("#toast"); t.textContent = msg; t.classList.remove("hidden");
  clearTimeout(t._t); t._t = setTimeout(()=>t.classList.add("hidden"), 2800);
}

async function api(path, opts={}){
  const headers = Object.assign({"Content-Type":"application/json"}, opts.headers||{});
  if(token) headers["Authorization"] = "Bearer " + token;
  const r = await fetch(API + path, Object.assign({}, opts, {headers}));
  const data = await r.json().catch(()=>({}));
  if(!r.ok) throw new Error(data.detail || "Error");
  return data;
}

// ---- login ----
$("#form-login").addEventListener("submit", async (e)=>{
  e.preventDefault();
  $("#login-error").textContent = "";
  try{
    const d = await api("/api/login", {method:"POST", body: JSON.stringify({
      usuario: $("#in-usuario").value.trim(), pin: $("#in-pin").value
    })});
    token = d.token; localStorage.setItem("goolnet_token", token);
    enterPanel();
  }catch(err){ $("#login-error").textContent = err.message; }
});

$("#btn-logout").addEventListener("click", ()=>{
  token = null; localStorage.removeItem("goolnet_token"); show("#view-login");
});

// ---- tabs ----
document.querySelectorAll(".tab").forEach(t=>{
  t.addEventListener("click", ()=>{
    document.querySelectorAll(".tab").forEach(x=>x.classList.remove("active"));
    t.classList.add("active");
    const tab = t.dataset.tab;
    $("#tab-conectados").classList.toggle("hidden", tab!=="conectados");
    $("#tab-clave").classList.toggle("hidden", tab!=="clave");
  });
});

// ---- panel ----
async function enterPanel(){
  show("#view-panel");
  try{ const e = await api("/api/estado"); $("#ssid-label").textContent = e.ssid || "WiFi"; }catch{}
  cargarDispositivos();
}

async function cargarDispositivos(){
  $("#lista").innerHTML = "<li class='hint'>Cargando…</li>";
  try{
    const d = await api("/api/dispositivos");
    $("#count").textContent = d.total;
    $("#lista").innerHTML = "";
    if(!d.dispositivos.length){ $("#lista").innerHTML = "<li class='hint'>Sin equipos reportados.</li>"; return; }
    d.dispositivos.forEach(h=>{
      const li = document.createElement("li");
      li.className = "item";
      li.innerHTML = `
        <span class="dot ${h.active?'':'off'}"></span>
        <div class="info">
          <div class="name">${h.hostname || "Equipo"}</div>
          <div class="mac">${h.mac} ${h.ip?("· "+h.ip):""}</div>
        </div>
        <span class="blk">Bloquear</span>`;
      li.addEventListener("click", ()=>bloquear(h.mac, h.hostname));
      $("#lista").appendChild(li);
    });
  }catch(err){ $("#lista").innerHTML = `<li class='error'>${err.message}</li>`; }
}

async function bloquear(mac, nombre){
  if(!confirm(`¿Bloquear "${nombre||mac}" de tu WiFi?`)) return;
  try{
    const d = await api("/api/bloquear", {method:"POST", body: JSON.stringify({mac})});
    toast(d.mensaje); cargarDispositivos();
  }catch(err){ toast(err.message); }
}

$("#btn-refresh").addEventListener("click", cargarDispositivos);

$("#form-wifi").addEventListener("submit", async (e)=>{
  e.preventDefault();
  $("#wifi-msg").textContent = "";
  const ssid = $("#in-ssid").value.trim();
  const clave = $("#in-clave").value;
  if(!ssid && !clave){ $("#wifi-msg").textContent = "Escribe un nombre o una clave."; return; }
  try{
    const d = await api("/api/wifi", {method:"POST", body: JSON.stringify({
      ssid: ssid||null, clave: clave||null
    })});
    $("#wifi-msg").textContent = d.mensaje;
    $("#in-clave").value = "";
  }catch(err){ $("#wifi-msg").textContent = err.message; }
});

// ---- arranque ----
if(token) enterPanel(); else show("#view-login");

// service worker
if("serviceWorker" in navigator){
  navigator.serviceWorker.register("service-worker.js").catch(()=>{});
}
