
(function(){
'use strict';
var APP_NAME = "TV Plus 2";
/* URL fija del servidor IPTV. Si se deja vacía, la app pide la URL al cliente. */
var SERVER_URL = "http://45.175.166.43:6490";

var $ = function(s){ return document.querySelector(s); };
var app = $('#app'), video = $('#video'), osd = $('#osd');
function esc(s){ return String(s == null ? '' : s).replace(/[&<>"']/g, function(c){ return {'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]; }); }
var store = {
  get: function(k, d){ try{ var v = localStorage.getItem('gtv_'+k); return v ? JSON.parse(v) : d; }catch(e){ return d; } },
  set: function(k, v){ try{ localStorage.setItem('gtv_'+k, JSON.stringify(v)); }catch(e){} }
};
var IS_TV = !!(window.tizen || window.webOS || window.PalmSystem || /Tizen|Web0S|webOS|SMART-TV/i.test(navigator.userAgent));

var DEMO_M3U = '#EXTM3U\n' +
 '#EXTINF:-1 group-title="Demostración",Big Buck Bunny (prueba)\nhttps://test-streams.mux.dev/x36xhzz/x36xhzz.m3u8\n' +
 '#EXTINF:-1 group-title="Demostración",Apple Bip Bop (prueba)\nhttps://devstreaming-cdn.apple.com/videos/streaming/examples/img_bipbop_adv_example_fmp4/master.m3u8\n' +
 '#EXTINF:-1 group-title="Demostración",Sintel (prueba)\nhttps://bitdash-a.akamaihd.net/content/sintel/hls/playlist.m3u8\n' +
 '#EXTINF:-1 group-title="Demostración",Tears of Steel (prueba)\nhttps://demo.unified-streaming.com/k8s/features/stable/video/tears-of-steel/tears-of-steel.ism/.m3u8\n';

var S = {
  acc:null, info:null, m3u:null, section:'live', cats:{}, items:{}, cat:null,
  list:[], shown:0, cur:null, fav:{live:[],vod:[],series:[]}, series:null,
  player:null, fmt:store.get('fmt','m3u8'), loginTab:'xtream', exitArmed:0,
  zoneMem:{}, lastFocus:null, epg:{}
};

/* ---------- utilidades ---------- */
function fetchT(url, ms){
  ms = ms || 20000;
  if (window.AbortController){
    var c = new AbortController(); var t = setTimeout(function(){ c.abort(); }, ms);
    return fetch(url, {signal:c.signal}).then(function(r){ clearTimeout(t); return r; }, function(e){ clearTimeout(t); throw e; });
  }
  return fetch(url);
}
function normServer(s){
  s = (s || '').trim();
  if (!/^https?:\/\//i.test(s)) s = 'http://' + s;
  return s.replace(/\/(player_api\.php|get\.php|panel_api\.php|xmltv\.php).*$/i, '').replace(/\/+$/, '');
}
function api(action, params){
  var q = 'username=' + encodeURIComponent(S.acc.user) + '&password=' + encodeURIComponent(S.acc.pass);
  if (action) q += '&action=' + action;
  params = params || {};
  Object.keys(params).forEach(function(k){ q += '&' + k + '=' + encodeURIComponent(params[k]); });
  return fetchT(S.acc.server + '/player_api.php?' + q).then(function(r){
    if (!r.ok) throw new Error('El servidor respondió con error ' + r.status);
    return r.json();
  });
}
function friendlyErr(e){
  if (e && e.name === 'AbortError') return 'El servidor no respondió a tiempo. Revisa la URL.';
  if (e instanceof TypeError) return 'No se pudo conectar con el servidor. Revisa la URL' +
    (location.protocol === 'https:' && !IS_TV ? '. (En esta vista previa web solo funcionan servidores https y los que permiten acceso desde navegador; instalada en el televisor funciona con cualquiera.)' : '.');
  return (e && e.message) || 'Ocurrió un error';
}
function b64(s){ try{ return decodeURIComponent(escape(atob(s))); }catch(e){ return s || ''; } }
function hm(t){ var d = new Date(t*1000); var h = d.getHours(), m = d.getMinutes(); return (h<10?'0':'')+h+':'+(m<10?'0':'')+m; }
function fmtTime(s){ s = Math.floor(s||0); var h=Math.floor(s/3600), m=Math.floor(s%3600/60), x=s%60; return (h?h+':':'')+(m<10&&h?'0':'')+m+':'+(x<10?'0':'')+x; }
var toastT;
function toast(m){ var t=$('#toast'); t.textContent=m; t.className='show'; clearTimeout(toastT); toastT=setTimeout(function(){ t.className=''; }, 2500); }
function img(src, alt){
  return (alt != null ? '<span class="ph">'+esc(String(alt).replace(/^[^A-Za-z0-9ÁÉÍÓÚÑáéíóúñ]+/,'').charAt(0).toUpperCase())+'</span>' : '') +
    (src ? '<img src="'+esc(src)+'" onerror="this.parentNode.removeChild(this)" alt="">' : '');
}
function cssq(v){ return String(v).replace(/["\\]/g, '\\$&'); }

/* ---------- cuentas ---------- */
function accounts(){ return store.get('accounts', []); }
function saveAccount(a){ var l = accounts().filter(function(x){ return x.id !== a.id; }); l.unshift(a); store.set('accounts', l.slice(0,10)); }
function removeAccount(id){ store.set('accounts', accounts().filter(function(x){ return x.id !== id; })); }

/* ---------- M3U ---------- */
function parseM3U(t){
  var lines = t.split(/\r?\n/), live = [], vod = [], cur = null;
  for (var i=0;i<lines.length;i++){
    var l = lines[i].trim(); if (!l) continue;
    if (l.indexOf('#EXTINF') === 0){
      var attrs = {}; l.replace(/([\w-]+)="([^"]*)"/g, function(m,k,v){ attrs[k]=v; });
      cur = { name:l.slice(l.lastIndexOf(',')+1).trim(), logo:attrs['tvg-logo']||'', group:attrs['group-title']||'Sin categoría' };
    } else if (l.charAt(0) !== '#' && cur){
      cur.url = l; cur.id = 'm' + (live.length + vod.length);
      (/\/(movie|series)\//.test(l) ? vod : live).push(cur); cur = null;
    }
  }
  return {live:live, vod:vod};
}

/* ---------- login ---------- */
function renderLogin(msg){
  S.acc = null; S.series = null;
  var acs = accounts();
  app.innerHTML = '<div class="login" data-zone="login"><div class="lbox">' +
    '<div class="brand"><div class="logo">▶</div><h1>'+esc(APP_NAME)+'</h1></div>' +
    (acs.length ? '<label class="lbl">Cuentas guardadas</label><div class="saved">' + acs.map(function(a){
      return '<button class="f ghost" data-act="useacc" data-v="'+esc(a.id)+'">▶ '+esc(a.name)+'</button>'; }).join('') + '</div>' : '') +
    (SERVER_URL ?
      '<label class="lbl">Usuario</label><input class="f in" id="l-user" autocapitalize="off" autocorrect="off" spellcheck="false">' +
      '<label class="lbl">Contraseña</label><input class="f in" id="l-pass" type="password">' +
      '<div class="row-btns"><button class="f primary" data-act="login">Entrar</button></div>'
    :
    '<label class="lbl">Agregar cuenta</label>' +
    '<div class="tabs"><button class="f tab '+(S.loginTab==='xtream'?'on':'')+'" data-act="ltab" data-v="xtream">Xtream Codes</button>' +
    '<button class="f tab '+(S.loginTab==='m3u'?'on':'')+'" data-act="ltab" data-v="m3u">Lista M3U</button></div>' +
    '<label class="lbl">Nombre de la cuenta</label><input class="f in" id="l-name" placeholder="Ej: Mi TV" value="Mi TV">' +
    (S.loginTab === 'xtream' ?
      '<label class="lbl">URL del servidor</label><input class="f in" id="l-server" placeholder="http://servidor.com:8080" autocapitalize="off" autocorrect="off" spellcheck="false">' +
      '<label class="lbl">Usuario</label><input class="f in" id="l-user" autocapitalize="off" autocorrect="off" spellcheck="false">' +
      '<label class="lbl">Contraseña</label><input class="f in" id="l-pass" type="password">'
    :
      '<label class="lbl">URL de la lista M3U</label><input class="f in" id="l-m3u" placeholder="http://servidor.com/lista.m3u" autocapitalize="off" autocorrect="off" spellcheck="false">'
    ) +
    '<div class="row-btns"><button class="f primary" data-act="login">Entrar</button>' +
    '<button class="f ghost" data-act="demo">Probar con canales de demostración</button></div>') +
    '<div class="err" id="l-err">'+esc(msg||'')+'</div>' +
    '<div class="hint">Usa las flechas del control para moverte y OK para elegir.</div>' +
    '</div></div>';
  focusEl(app.querySelector(acs.length ? '.saved .f' : '#l-user' + (SERVER_URL ? '' : ', #l-server, #l-m3u')));
}
function val(id){ var e = $('#'+id); return e ? e.value.trim() : ''; }
function submitLogin(){
  var name = val('l-name') || 'Mi TV', a;
  if (SERVER_URL){
    if (!val('l-user') || !val('l-pass')) return setErr('Escribe tu usuario y tu contraseña.');
    var sv = normServer(SERVER_URL);
    a = {type:'xtream', name:val('l-user'), server:sv, user:val('l-user'), pass:val('l-pass'), id:'x:'+sv+'|'+val('l-user')};
  } else if (S.loginTab === 'xtream'){
    if (!val('l-server') || !val('l-user') || !val('l-pass')) return setErr('Completa la URL, el usuario y la contraseña.');
    var server = normServer(val('l-server'));
    a = {type:'xtream', name:name, server:server, user:val('l-user'), pass:val('l-pass'), id:'x:'+server+'|'+val('l-user')};
  } else {
    if (!val('l-m3u')) return setErr('Escribe la URL de la lista M3U.');
    a = {type:'m3u', name:name, m3u:val('l-m3u'), id:'m:'+val('l-m3u')};
  }
  doLogin(a);
}
function setErr(m){ var e = $('#l-err'); if (e) e.textContent = m; }
function doLogin(acc){
  setErr('Conectando…');
  var p;
  if (acc.type === 'xtream'){
    S.acc = acc;
    p = api(null).then(function(d){
      if (!d || !d.user_info || d.user_info.auth === 0 || d.user_info.auth === '0') throw new Error('Usuario o contraseña incorrectos.');
      if (d.user_info.status && d.user_info.status !== 'Active') throw new Error('La cuenta está: ' + d.user_info.status);
      S.info = d.user_info; S.m3u = null;
    });
  } else {
    p = (acc.type === 'demo' ? Promise.resolve(DEMO_M3U) : fetchT(acc.m3u, 40000).then(function(r){ if(!r.ok) throw new Error('No se pudo descargar la lista ('+r.status+').'); return r.text(); }))
      .then(function(t){
        var m = parseM3U(t);
        if (!m.live.length && !m.vod.length) throw new Error('La lista no tiene canales.');
        S.acc = acc; S.m3u = m; S.info = null;
      });
  }
  p.then(function(){
    if (acc.type !== 'demo') saveAccount(acc);
    S.cats = {}; S.items = {}; S.epg = {}; S.zoneMem = {};
    S.fav = store.get('fav_'+acc.id, {live:[],vod:[],series:[]});
    openSection('live', true);
  }).catch(function(e){ S.acc = null; setErr(friendlyErr(e)); });
}

/* ---------- datos ---------- */
function sections(){
  var l = [['live','📺','Televisión'],['vod','🎬','Películas']];
  if (S.acc.type === 'xtream') l.push(['series','🎞️','Series']);
  l.push(['search','🔍','Buscar'],['account','👤','Cuenta']);
  return l;
}
function getCats(sec){
  if (S.cats[sec]) return Promise.resolve(S.cats[sec]);
  var p;
  if (S.acc.type === 'xtream'){
    p = api({live:'get_live_categories',vod:'get_vod_categories',series:'get_series_categories'}[sec]).then(function(d){
      return (Array.isArray(d)?d:[]).map(function(c){ return {id:String(c.category_id), name:c.category_name}; });
    });
  } else {
    var seen = {}, cats = [];
    (S.m3u[sec] || []).forEach(function(i){ if(!seen[i.group]){ seen[i.group]=1; cats.push({id:i.group,name:i.group}); } });
    p = Promise.resolve(cats);
  }
  return p.then(function(c){ return S.cats[sec] = [{id:'*fav',name:'★ Favoritos'},{id:'*all',name:'Todos'}].concat(c); });
}
function norm(sec, x){
  if (sec === 'live') return {id:String(x.stream_id), name:x.name, logo:x.stream_icon||'', kind:'live', num:x.num||''};
  if (sec === 'vod') return {id:String(x.stream_id), name:x.name, logo:x.stream_icon||'', kind:'vod', ext:x.container_extension||'mp4', rating:x.rating||''};
  return {id:String(x.series_id), name:x.name, logo:x.cover||'', kind:'series', plot:x.plot||'', rating:x.rating||''};
}
function getItems(sec, cat){
  if (cat === '*fav') return getItems(sec, '*all').then(function(all){ var f = S.fav[sec]||[]; return all.filter(function(i){ return f.indexOf(i.id) >= 0; }); });
  var key = sec + '|' + cat;
  if (S.items[key]) return Promise.resolve(S.items[key]);
  var p;
  if (S.acc.type === 'xtream'){
    p = api({live:'get_live_streams',vod:'get_vod_streams',series:'get_series'}[sec], cat === '*all' ? {} : {category_id:cat}).then(function(d){
      return (Array.isArray(d)?d:[]).map(function(x){ return norm(sec, x); });
    });
  } else {
    p = Promise.resolve((S.m3u[sec]||[]).filter(function(i){ return cat === '*all' || i.group === cat; }).map(function(i){
      return {id:i.id, name:i.name, logo:i.logo, kind:sec, url:i.url, num:''}; }));
  }
  return p.then(function(l){ return S.items[key] = l; });
}
function streamUrl(it, alt){
  if (it.url) return it.url;
  var s = S.acc.server, u = encodeURIComponent(S.acc.user), p = encodeURIComponent(S.acc.pass);
  if (it.kind === 'live'){ var f = alt ? (S.fmt === 'm3u8' ? 'ts' : 'm3u8') : S.fmt; return s+'/live/'+u+'/'+p+'/'+it.id+'.'+f; }
  if (it.kind === 'vod') return s+'/movie/'+u+'/'+p+'/'+it.id+'.'+it.ext;
  return s+'/series/'+u+'/'+p+'/'+it.id+'.'+it.ext;
}
function loadEpg(it){
  if (S.acc.type !== 'xtream' || it.kind !== 'live') return Promise.resolve('');
  var c = S.epg[it.id];
  if (c && Date.now() - c.t < 300000) return Promise.resolve(c.h);
  return api('get_short_epg', {stream_id:it.id, limit:2}).then(function(d){
    var l = (d && d.epg_listings) || [];
    var h = l.length ? l.map(function(p,i){
      return '<div class="prog '+(i?'next':'now')+'"><b>'+(i?'Después':'Ahora')+' · '+hm(p.start_timestamp)+' – '+hm(p.stop_timestamp)+'</b><span>'+esc(b64(p.title))+'</span></div>';
    }).join('') : '<div class="muted">Sin guía de programación</div>';
    S.epg[it.id] = {t:Date.now(), h:h}; return h;
  }).catch(function(){ return ''; });
}
function favKey(it){ return it.kind === 'ep' ? 'series' : it.kind; }
function isFav(it){ return (S.fav[favKey(it)]||[]).indexOf(it.id) >= 0; }
function toggleFav(it){
  if (!it || it.kind === 'ep') return;
  var k = favKey(it), l = S.fav[k] = S.fav[k] || [], i = l.indexOf(it.id);
  if (i >= 0){ l.splice(i,1); toast('Quitado de favoritos'); } else { l.push(it.id); toast('★ Agregado a favoritos'); }
  store.set('fav_'+S.acc.id, S.fav);
  var b = app.querySelector('[data-act="fav"]'); if (b) b.textContent = isFav(it) ? '★ Quitar de favoritos' : '☆ Agregar a favoritos';
  var idx = S.list.indexOf(it);
  if (idx >= 0){ var el = app.querySelector('#list [data-i="'+idx+'"]'); if (el){ var st = el.querySelector('.star'); if (isFav(it) && !st) el.insertAdjacentHTML('beforeend','<span class="star">★</span>'); if (!isFav(it) && st) st.parentNode.removeChild(st); } }
}

/* ---------- pantalla principal ---------- */
function renderHome(){
  var exp = '';
  if (S.info) exp = S.info.exp_date ? new Date(S.info.exp_date*1000).toLocaleDateString('es-EC') : 'Sin vencimiento';
  app.innerHTML = '<div class="home sec-'+S.section+'">' +
    '<nav class="side" data-zone="side"><div class="brand sm"><div class="logo">▶</div><b>'+esc(APP_NAME)+'</b></div>' +
    sections().map(function(s){ return '<button class="f nav '+(S.section===s[0]?'on':'')+'" data-act="sec" data-v="'+s[0]+'"><span>'+s[1]+'</span>'+s[2]+'</button>'; }).join('') +
    '<div class="who">'+esc(S.acc.name)+(exp ? '<br><small>Vence: '+esc(exp)+'</small>' : '')+'</div></nav>' +
    '<section class="cats" id="cats" data-zone="cats"></section>' +
    '<section class="list" id="list" data-zone="list"></section>' +
    '<aside class="info" id="info" data-zone="info"></aside></div>';
}
function openSection(sec, focusContent){
  S.section = sec; S.series = null; S.cur = null; S.zoneMem.cats = S.zoneMem.list = S.zoneMem.info = null;
  renderHome();
  S.zoneMem.side = app.querySelector('.nav.on');
  if (!focusContent) focusEl(S.zoneMem.side);
  if (sec === 'search') return renderSearch(focusContent);
  if (sec === 'account') return renderAccount();
  var cats = $('#cats'); cats.innerHTML = '<div class="loading">Cargando…</div>';
  getCats(sec).then(function(cs){
    if (S.section !== sec) return;
    cats.innerHTML = '<h3>Categorías</h3>' + cs.map(function(c){ return '<button class="f cat" data-act="cat" data-v="'+esc(c.id)+'">'+esc(c.name)+'</button>'; }).join('');
    var start = (S.fav[sec]||[]).length ? '*fav' : '*all';
    openCat(start).then(function(){ if (focusContent) focusEl(app.querySelector('#list .f') || app.querySelector('.cat.on')); });
  }).catch(function(e){ cats.innerHTML = '<div class="err">'+esc(friendlyErr(e))+'</div>'; });
}
function openCat(id){
  S.cat = id; S.series = null;
  Array.prototype.forEach.call(app.querySelectorAll('.cat'), function(b){ var on = b.getAttribute('data-v') === id; b.classList.toggle('on', on); if (on) S.zoneMem.cats = b; });
  var list = $('#list'); list.className = 'list'; list.innerHTML = '<div class="loading">Cargando…</div>';
  var sec = S.section;
  return getItems(sec, id).then(function(items){
    if (S.cat !== id || S.section !== sec) return;
    S.list = items; S.shown = 0; S.zoneMem.list = null;
    list.className = 'list ' + (sec === 'live' ? 'rows' : 'grid'); list.innerHTML = ''; list.scrollTop = 0;
    if (!items.length){ list.innerHTML = '<div class="empty">' + (id === '*fav' ? 'Aún no tienes favoritos. Elige un canal y usa «Agregar a favoritos» (o el botón rojo del control).' : 'No hay contenido en esta categoría.') + '</div>'; return; }
    renderMore();
    renderInfo(items[0]);
  }).catch(function(e){ list.innerHTML = '<div class="err">'+esc(friendlyErr(e))+'</div>'; });
}
function itemHTML(it, i, asRow){
  var star = isFav(it) ? '<span class="star">★</span>' : '';
  if (asRow || it.kind === 'live')
    return '<button class="f row" data-act="item" data-i="'+i+'">'+(it.num?'<span class="num">'+esc(it.num)+'</span>':'')+'<span class="lg">'+img(it.logo)+'</span><span class="nm">'+esc(it.name)+'</span>'+(asRow&&it.kind!=='live'?'<span class="kind">'+(it.kind==='vod'?'Película':'Serie')+'</span>':'')+star+'</button>';
  return '<button class="f card" data-act="item" data-i="'+i+'"><span class="poster">'+img(it.logo, it.name)+'</span><span class="nm">'+esc(it.name)+'</span>'+star+'</button>';
}
function renderMore(asRow){
  var list = $('#list'), more = list.querySelector('.more');
  if (more) more.parentNode.removeChild(more);
  var chunk = S.list.slice(S.shown, S.shown + 120), start = S.shown, h = '';
  for (var i=0;i<chunk.length;i++) h += itemHTML(chunk[i], start+i, asRow);
  list.insertAdjacentHTML('beforeend', h); S.shown += chunk.length;
  if (S.shown < S.list.length) list.insertAdjacentHTML('beforeend', '<button class="f more" data-act="more">Ver más ('+(S.list.length-S.shown)+')</button>');
  return list.querySelector('[data-i="'+start+'"]');
}
var infoT;
function onFocusItem(it){ if (!it || it === S.cur) return; S.cur = it; clearTimeout(infoT); infoT = setTimeout(function(){ renderInfo(it); }, 200); }
function renderInfo(it){
  var el = $('#info'); if (!el || !it) return; S.cur = it;
  var ae = document.activeElement, keep = ae && el.contains(ae) ? ae.getAttribute('data-act') : null;
  var openTxt = it.kind === 'series' ? 'Ver episodios' : (it.kind === 'live' ? 'Ver canal' : 'Ver ahora');
  el.innerHTML = '<div class="pv">'+img(it.logo, it.name)+'</div><h2>'+esc(it.name)+'</h2>' +
    (it.rating ? '<div class="meta">⭐ '+esc(it.rating)+'</div>' : '') +
    '<div id="epg"></div><p class="plot" id="plot">'+esc(it.plot||'')+'</p>' +
    '<div class="btns"><button class="f primary" data-act="open">▶ '+openTxt+'</button>' +
    '<button class="f ghost" data-act="fav">'+(isFav(it)?'★ Quitar de favoritos':'☆ Agregar a favoritos')+'</button></div>';
  if (keep) focusEl(el.querySelector('[data-act="'+keep+'"]'));
  if (it.kind === 'live') loadEpg(it).then(function(h){ var e = $('#epg'); if (e && S.cur === it) e.innerHTML = h; });
  if (it.kind === 'vod' && S.acc.type === 'xtream' && !it._vi){
    it._vi = true;
    api('get_vod_info', {vod_id:it.id}).then(function(d){
      var inf = (d && d.info) || {}; it.plot = inf.plot || inf.description || '';
      if (d && d.movie_data && d.movie_data.container_extension) it.ext = d.movie_data.container_extension;
      var p = $('#plot'); if (p && S.cur === it) p.textContent = it.plot;
    }).catch(function(){});
  }
}
function openItem(it, list, idx){
  if (!it) return;
  if (it.kind === 'series') return openSeries(it);
  play(list, idx);
}

/* ---------- series ---------- */
function openSeries(it){
  var list = $('#list');
  S.series = {it:it, idx:S.list.indexOf(it)};
  list.className = 'list eps'; list.innerHTML = '<div class="loading">Cargando episodios…</div>';
  api('get_series_info', {series_id:it.id}).then(function(d){
    if (!S.series || S.series.it !== it) return;
    var eps = (d && d.episodes) || {};
    if (Array.isArray(eps)){ var o = {}; eps.forEach(function(arr){ if (arr && arr[0]) o[arr[0].season] = arr; }); eps = o; }
    S.series.eps = eps;
    S.series.seasons = Object.keys(eps).sort(function(a,b){ return a-b; });
    if (d && d.info && d.info.plot){ it.plot = d.info.plot; var p = $('#plot'); if (p) p.textContent = it.plot; }
    if (!S.series.seasons.length){ list.innerHTML = '<div class="empty">Esta serie no tiene episodios.</div>'; return; }
    renderSeason(S.series.seasons[0], true);
  }).catch(function(e){ list.innerHTML = '<div class="err">'+esc(friendlyErr(e))+'</div>'; });
}
function renderSeason(sn, focus){
  var s = S.series, list = $('#list'); s.season = sn;
  s.list = (s.eps[sn] || []).map(function(e){
    return {id:String(e.id), name:(e.episode_num ? e.episode_num+'. ' : '') + (e.title || 'Episodio'), ext:e.container_extension||'mp4', kind:'ep', logo:(e.info && e.info.movie_image) || s.it.logo};
  });
  list.innerHTML = '<h3><button class="f ghost" data-act="sback">← Volver</button> &nbsp;'+esc(s.it.name)+'</h3>' +
    '<div class="seasons">' + s.seasons.map(function(x){ return '<button class="f tab '+(x===sn?'on':'')+'" data-act="season" data-v="'+esc(x)+'">Temporada '+esc(x)+'</button>'; }).join('') + '</div>' +
    '<div class="eplist">' + s.list.map(function(e,i){ return '<button class="f row" data-act="ep" data-i="'+i+'"><span class="nm">'+esc(e.name)+'</span></button>'; }).join('') + '</div>';
  if (focus) focusEl(list.querySelector('.eplist .f') || list.querySelector('.f'));
}
function closeSeries(){
  var idx = S.series ? S.series.idx : 0; S.series = null;
  var list = $('#list'); list.className = 'list grid'; list.innerHTML = ''; S.shown = 0;
  while (S.shown <= idx && S.shown < S.list.length) renderMore();
  focusEl(list.querySelector('[data-i="'+idx+'"]') || list.querySelector('.f'));
}

/* ---------- búsqueda ---------- */
var searchT;
function renderSearch(focus){
  $('#cats').innerHTML = '<div class="sbox"><h3>Buscar</h3><input class="f in" id="q" placeholder="Nombre del canal, película o serie" autocapitalize="off" autocorrect="off" spellcheck="false"><div class="hint">Escribe al menos 2 letras.</div></div>';
  $('#list').innerHTML = '<div class="empty">Los resultados aparecerán aquí.</div>';
  var q = $('#q');
  q.addEventListener('input', function(){ clearTimeout(searchT); searchT = setTimeout(function(){ doSearch(q.value); }, 450); });
  if (focus) focusEl(q);
}
function doSearch(q){
  q = q.trim().toLowerCase();
  var list = $('#list');
  if (q.length < 2){ list.innerHTML = '<div class="empty">Escribe al menos 2 letras.</div>'; return; }
  list.innerHTML = '<div class="loading">Buscando…</div>';
  var secs = S.acc.type === 'xtream' ? ['live','vod','series'] : ['live','vod'];
  Promise.all(secs.map(function(s){ return getItems(s,'*all').catch(function(){ return []; }); })).then(function(rs){
    if (S.section !== 'search') return;
    var res = [];
    rs.forEach(function(r){ r.forEach(function(it){ if (res.length < 300 && String(it.name).toLowerCase().indexOf(q) >= 0) res.push(it); }); });
    S.list = res; S.shown = 0; list.className = 'list rows'; list.innerHTML = '';
    if (!res.length){ list.innerHTML = '<div class="empty">No se encontró nada con «'+esc(q)+'».</div>'; return; }
    renderMore(true);
  });
}

/* ---------- cuenta ---------- */
function renderAccount(){
  var a = S.acc, i = S.info || {}, list = $('#list');
  var rows = [['Cuenta', a.name]];
  if (a.type === 'xtream'){
    if (!SERVER_URL) rows.push(['Servidor', a.server]);
    rows.push(['Usuario', a.user], ['Estado', i.status || '—'],
      ['Vence', i.exp_date ? new Date(i.exp_date*1000).toLocaleDateString('es-EC') : 'Sin vencimiento'],
      ['Conexiones', (i.active_cons || 0) + ' de ' + (i.max_connections || '—')]);
  } else rows.push(['Lista', a.type === 'demo' ? 'Demostración' : a.m3u]);
  list.className = 'list acct';
  list.innerHTML = '<h3>Mi cuenta</h3>' + rows.map(function(r){ return '<div class="kv"><span>'+esc(r[0])+'</span>'+esc(r[1])+'</div>'; }).join('') +
    (a.type === 'xtream' ? '<h3 style="margin-top:2rem">Formato de transmisión en vivo</h3><div class="tabs">' +
      '<button class="f tab '+(S.fmt==='m3u8'?'on':'')+'" data-act="fmt" data-v="m3u8">HLS (m3u8)</button>' +
      '<button class="f tab '+(S.fmt==='ts'?'on':'')+'" data-act="fmt" data-v="ts">MPEG-TS (ts)</button></div>' +
      '<div class="hint">Si un canal no carga, prueba cambiando el formato.</div>' : '') +
    '<div><button class="f ghost" data-act="reload">⟳ Recargar listas</button>' +
    '<button class="f ghost" data-act="logout">⇄ Cambiar de cuenta</button>' +
    (a.type !== 'demo' ? '<button class="f ghost" data-act="delacc">🗑 Eliminar esta cuenta</button>' : '') + '</div>';
  $('#info').innerHTML = '<div class="pv"><div class="logo" style="width:6rem;height:6rem;font-size:3rem;border-radius:1.4rem">▶</div></div><h2>'+esc(APP_NAME)+'</h2><p class="plot">Versión 1.0</p>';
}

/* ---------- reproductor ---------- */
var hlsObj = null, hlsP = null, osdT;
function loadHls(){
  if (window.Hls) return Promise.resolve(window.Hls);
  if (!hlsP) hlsP = new Promise(function(res){
    var s = document.createElement('script'); s.src = 'https://cdn.jsdelivr.net/npm/hls.js@1/dist/hls.min.js';
    s.onload = function(){ res(window.Hls || null); }; s.onerror = function(){ res(null); };
    document.head.appendChild(s);
  });
  return hlsP;
}
function play(list, idx){
  S.lastFocus = document.activeElement;
  S.player = {list:list, idx:idx, alt:false};
  document.body.classList.add('playing');
  startStream(false); showOsd();
}
function stopVideo(){
  if (hlsObj){ try{ hlsObj.destroy(); }catch(e){} hlsObj = null; }
  try{ video.pause(); }catch(e){}
  video.removeAttribute('src'); try{ video.load(); }catch(e){}
}
function startStream(alt){
  var p = S.player, it = p.list[p.idx], url = streamUrl(it, alt), gen = p.gen = (p.gen||0) + 1;
  p.alt = alt; stopVideo(); osdMsg('Cargando…');
  var isHls = /\.m3u8(\?|$)/i.test(url);
  var native = video.canPlayType('application/vnd.apple.mpegurl');
  if (isHls && !native && !IS_TV){
    loadHls().then(function(H){
      if (!S.player || S.player.gen !== gen) return;
      if (H && H.isSupported()){
        hlsObj = new H({enableWorker:true, lowLatencyMode:false});
        hlsObj.on(H.Events.ERROR, function(e, d){ if (d && d.fatal) onPlayErr(); });
        hlsObj.loadSource(url); hlsObj.attachMedia(video);
        video.play().catch(function(){});
      } else { video.src = url; video.play().catch(function(){}); }
    });
  } else { video.src = url; var pr = video.play(); if (pr && pr.catch) pr.catch(function(){}); }
}
function onPlayErr(){
  var p = S.player; if (!p) return;
  var it = p.list[p.idx];
  if (it.kind === 'live' && !it.url && !p.alt) return startStream(true);
  osdMsg('No se pudo reproducir. Prueba otro canal o cambia el formato en Cuenta.');
}
video.addEventListener('error', function(){ if (S.player && video.getAttribute('src')) onPlayErr(); });
video.addEventListener('waiting', function(){ if (S.player) osdMsg('Cargando…'); });
video.addEventListener('playing', function(){ if (S.player) osdMsg(''); });
video.addEventListener('timeupdate', function(){
  var b = $('#o-bar'), t = $('#o-time');
  if (b && video.duration && isFinite(video.duration)) b.style.width = (video.currentTime / video.duration * 100) + '%';
  if (t && video.duration && isFinite(video.duration)) t.textContent = fmtTime(video.currentTime) + ' / ' + fmtTime(video.duration);
});
video.addEventListener('click', function(){ showOsd(); });
function osdMsg(m){ var e = $('#o-msg'); if (e) e.textContent = m; if (m) osdKeep(); }
function osdKeep(){ osd.className = 'show'; clearTimeout(osdT); osdT = setTimeout(function(){ if (!(video.paused && S.player && S.player.list[S.player.idx].kind !== 'live')) osd.className = ''; }, 5000); }
function showOsd(){
  var p = S.player; if (!p) return; var it = p.list[p.idx], live = it.kind === 'live';
  var msg = $('#o-msg') ? $('#o-msg').textContent : '';
  osd.innerHTML = '<button class="o-close" data-act="close">✕ Cerrar</button>' +
    '<div class="o-name">'+(it.num?'<span class="num">'+esc(it.num)+'</span>':'')+esc(it.name)+'</div><div id="o-epg"></div><div id="o-msg" class="o-msg">'+esc(msg)+'</div>' +
    (!live ? '<div class="bar"><i id="o-bar"></i></div><div id="o-time" class="o-time"></div>' : '') +
    '<div class="o-hint">'+(live ? '▲ ▼ Cambiar canal · OK Información · ATRÁS Salir' : '◀ ▶ Retroceder / Adelantar 10 s · OK Pausa · ATRÁS Salir')+'</div>';
  osdKeep();
  if (live) loadEpg(it).then(function(h){ var e = $('#o-epg'); if (e && S.player && S.player.list[S.player.idx] === it) e.innerHTML = h; });
}
function zap(d){
  var p = S.player, n = p.list.length; if (n < 2) return;
  p.idx = (p.idx + d + n) % n; startStream(false); showOsd();
}
function seek(s){ try{ if (video.duration && isFinite(video.duration)) video.currentTime = Math.max(0, Math.min(video.duration - 1, video.currentTime + s)); }catch(e){} showOsd(); }
function togglePause(){ if (video.paused) video.play(); else video.pause(); showOsd(); }
function closePlayer(){
  var p = S.player; S.player = null; stopVideo();
  document.body.classList.remove('playing'); osd.className = ''; osd.innerHTML = '';
  var el = S.lastFocus;
  if (p && p.list === S.list && p.list[p.idx].kind === 'live'){
    var idx = p.idx; while (S.shown <= idx && S.shown < S.list.length) renderMore(S.section === 'search');
    var t = app.querySelector('#list [data-i="'+idx+'"]'); if (t) el = t;
  }
  if (el && document.body.contains(el)) focusEl(el);
}
function playerKey(e, k){
  var it = S.player.list[S.player.idx], live = it.kind === 'live';
  var h = {
    38: function(){ live ? zap(-1) : showOsd(); }, 40: function(){ live ? zap(1) : showOsd(); },
    427: function(){ zap(1); }, 33: function(){ zap(1); }, 428: function(){ zap(-1); }, 34: function(){ zap(-1); },
    37: function(){ live ? showOsd() : seek(-10); }, 39: function(){ live ? showOsd() : seek(10); },
    412: function(){ seek(-30); }, 417: function(){ seek(30); },
    13: function(){ live ? showOsd() : togglePause(); },
    415: function(){ video.play(); showOsd(); }, 19: function(){ video.pause(); showOsd(); }, 10252: togglePause, 32: togglePause,
    413: closePlayer, 403: function(){ toggleFav(it); }
  }[k];
  if (h){ e.preventDefault(); h(); }
}

/* ---------- navegación con control remoto ---------- */
function zoneOf(e){ var z = e && e.closest ? e.closest('[data-zone]') : null; return z ? z.getAttribute('data-zone') : ''; }
function focusEl(e){
  if (!e) return;
  try{ e.focus({preventScroll:true}); }catch(x){ e.focus(); }
  try{ e.scrollIntoView({block:'nearest', inline:'nearest'}); }catch(x){ e.scrollIntoView(false); }
}
function visibleEls(){
  return Array.prototype.filter.call(app.querySelectorAll('.f'), function(e){ return e.offsetParent !== null && !e.disabled; });
}
function move(k){
  var cur = document.activeElement, els = visibleEls();
  if (!cur || !cur.classList || !cur.classList.contains('f') || !app.contains(cur)){ focusEl(els[0]); return; }
  var c = cur.getBoundingClientRect(), cx = c.left + c.width/2, cy = c.top + c.height/2, z = zoneOf(cur), horiz = (k === 37 || k === 39);
  function pick(cands){
    var best = null, bd = Infinity;
    cands.forEach(function(e){
      var r = e.getBoundingClientRect(), x = r.left + r.width/2, y = r.top + r.height/2, p, s;
      var gx = Math.max(0, r.left - c.right, c.left - r.right), gy = Math.max(0, r.top - c.bottom, c.top - r.bottom);
      if (k === 39){ if (r.left < c.right - 4) return; p = r.left - c.right; s = gy * 3 + Math.abs(r.top - c.top) * 0.1; }
      else if (k === 37){ if (r.right > c.left + 4) return; p = c.left - r.right; s = gy * 3 + Math.abs(r.top - c.top) * 0.1; }
      else if (k === 40){ if (r.top < c.bottom - 4) return; p = r.top - c.bottom; s = gx * 3 + Math.abs(r.left - c.left) * 0.1; }
      else { if (r.bottom > c.top + 4) return; p = c.top - r.bottom; s = gx * 3 + Math.abs(r.left - c.left) * 0.1; }
      var d = p + s;
      if (d < bd){ bd = d; best = e; }
    });
    return best;
  }
  var same = els.filter(function(e){ return e !== cur && zoneOf(e) === z; });
  var t = pick(same);
  if (!t && horiz){
    var others = els.filter(function(e){ return zoneOf(e) !== z; });
    var cand = pick(others);
    if (cand){
      var mem = S.zoneMem[zoneOf(cand)];
      if (mem && document.body.contains(mem) && mem.offsetParent !== null){
        var mr = mem.getBoundingClientRect(), pr = mem.closest('[data-zone]').getBoundingClientRect();
        if (mr.bottom > pr.top && mr.top < pr.bottom) cand = mem;
      }
    }
    t = cand;
  }
  if (t) focusEl(t);
}
function isTyping(){ var a = document.activeElement; return a && a.tagName === 'INPUT'; }

document.addEventListener('focusin', function(e){
  var t = e.target; if (!t || !t.getAttribute) return;
  var z = zoneOf(t); if (z) S.zoneMem[z] = t;
  var act = t.getAttribute('data-act');
  if (act === 'item') onFocusItem(S.list[+t.getAttribute('data-i')]);
  if (act === 'more'){ var first = renderMore(S.section === 'search'); if (first) focusEl(first); }
});

function act(el){
  var a = el.getAttribute('data-act'), v = el.getAttribute('data-v'), i = +el.getAttribute('data-i');
  switch (a){
    case 'ltab': S.loginTab = v; renderLogin(); focusEl(app.querySelector('[data-act="ltab"][data-v="'+v+'"]')); break;
    case 'login': submitLogin(); break;
    case 'demo': doLogin({type:'demo', name:'Demostración', id:'demo'}); break;
    case 'useacc': var ac = accounts().filter(function(x){ return x.id === v; })[0]; if (ac) doLogin(ac); break;
    case 'sec': if (v !== S.section || S.series) openSection(v); break;
    case 'cat': openCat(v).then(function(){ if (S.list.length) S.zoneMem.list = null; }); break;
    case 'item': var it = S.list[i]; renderInfo(it); openItem(it, S.list, i); break;
    case 'open': if (S.cur) openItem(S.cur, S.list, Math.max(0, S.list.indexOf(S.cur))); break;
    case 'fav': toggleFav(S.cur); break;
    case 'more': var f = renderMore(S.section === 'search'); if (f) focusEl(f); break;
    case 'season': renderSeason(v, false); focusEl(app.querySelector('[data-act="season"][data-v="'+cssq(v)+'"]')); break;
    case 'ep': if (S.series) play(S.series.list, i); break;
    case 'sback': closeSeries(); break;
    case 'close': closePlayer(); break;
    case 'fmt': S.fmt = v; store.set('fmt', v); renderAccount(); focusEl(app.querySelector('[data-act="fmt"][data-v="'+v+'"]')); break;
    case 'reload': S.cats = {}; S.items = {}; S.epg = {}; toast('Listas recargadas'); break;
    case 'logout': renderLogin(); break;
    case 'delacc': removeAccount(S.acc.id); renderLogin(); break;
  }
}
document.addEventListener('click', function(e){
  var el = e.target.closest ? e.target.closest('[data-act]') : null;
  if (el){ e.preventDefault(); act(el); }
});

function exitApp(){
  try{ if (window.tizen){ tizen.application.getCurrentApplication().exit(); return; } }catch(e){}
  try{ if (window.AndroidApp){ window.AndroidApp.exit(); return; } }catch(e){}
  try{ window.close(); }catch(e){}
}
function onBack(){
  if (S.player) return closePlayer();
  if (S.acc && S.series) return closeSeries();
  var a = document.activeElement;
  if (S.acc && a && zoneOf(a) !== 'side') return focusEl(app.querySelector('.nav.on'));
  if (Date.now() - S.exitArmed < 2500) return exitApp();
  S.exitArmed = Date.now(); toast('Presiona ATRÁS otra vez para salir');
}
window.appBack = onBack;

document.addEventListener('keydown', function(e){
  var k = e.keyCode;
  if (k === 10009 || k === 461 || k === 27 || (k === 8 && !isTyping())){ e.preventDefault(); return onBack(); }
  if (S.player) return playerKey(e, k);
  if (k === 403 || (k === 70 && !isTyping() && S.acc)){ e.preventDefault(); return toggleFav(S.cur); }
  if (k >= 37 && k <= 40){
    if (isTyping() && (k === 37 || k === 39)){
      var inp = document.activeElement, atEdge = k === 37 ? inp.selectionStart === 0 : inp.selectionEnd === inp.value.length;
      if (!atEdge) return;
    }
    e.preventDefault(); return move(k);
  }
  if (k === 13 && isTyping()){
    e.preventDefault();
    if (document.activeElement.id === 'q') return doSearch(document.activeElement.value);
    if (document.activeElement.id === 'l-pass' || document.activeElement.id === 'l-m3u') return submitLogin();
    return move(40);
  }
});

/* teclas especiales en Samsung (Tizen) */
try{
  if (window.tizen && tizen.tvinputdevice){
    ['MediaPlayPause','MediaPlay','MediaPause','MediaStop','MediaFastForward','MediaRewind','ChannelUp','ChannelDown','ColorF0Red'].forEach(function(n){
      try{ tizen.tvinputdevice.registerKey(n); }catch(e){}
    });
  }
}catch(e){}

/* inicio: entra directo con la última cuenta usada */
var accs = accounts();
renderLogin();
if (accs.length && store.get('autologin', true)) doLogin(accs[0]);
})();
