package ec.goolnet.tecnicos;

import android.Manifest;
import android.app.Activity;
import android.content.Context;
import android.content.Intent;
import android.content.pm.PackageManager;
import android.location.Location;
import android.location.LocationManager;
import android.net.Uri;
import android.os.Build;
import android.os.Bundle;
import android.os.PowerManager;
import android.provider.Settings;
import android.webkit.JavascriptInterface;
import android.webkit.WebChromeClient;
import android.webkit.WebSettings;
import android.webkit.WebView;
import android.webkit.WebViewClient;

import org.json.JSONObject;

public class MainActivity extends Activity {
    private static final int PERM_UBIC = 1, PERM_FONDO = 2, PERM_NOTIF = 3;
    private WebView web;

    @Override
    protected void onCreate(Bundle b) {
        super.onCreate(b);
        getWindow().setStatusBarColor(0xFF3B7A8C);
        web = new WebView(this);
        WebSettings s = web.getSettings();
        s.setJavaScriptEnabled(true);
        s.setDomStorageEnabled(true);
        web.setWebViewClient(new WebViewClient());
        web.setWebChromeClient(new WebChromeClient());
        web.addJavascriptInterface(new Puente(), "Nativo");
        setContentView(web);
        web.loadUrl("file:///android_asset/www/index.html");
        if (Prefs.logueado(this)) Programador.iniciarSiToca(this);
    }

    @Override
    protected void onResume() {
        super.onResume();
        if (web != null) web.evaluateJavascript("window.refrescar && window.refrescar()", null);
    }

    @Override
    public void onBackPressed() {
        web.evaluateJavascript("window.atras ? window.atras() : false", v -> {
            if (!"true".equals(v)) moveTaskToBack(true);
        });
    }

    private void js(String codigo) {
        runOnUiThread(() -> web.evaluateJavascript(codigo, null));
    }

    private void responder(String id, int codigo, String cuerpo) {
        js("window._resp(" + JSONObject.quote(id) + "," + codigo + "," + JSONObject.quote(cuerpo) + ")");
    }

    // ------------------------------------------------------------ permisos

    private boolean tiene(String p) { return checkSelfPermission(p) == PackageManager.PERMISSION_GRANTED; }

    private boolean ubicOk() { return tiene(Manifest.permission.ACCESS_FINE_LOCATION); }

    private boolean fondoOk() {
        return Build.VERSION.SDK_INT < 29 || tiene(Manifest.permission.ACCESS_BACKGROUND_LOCATION);
    }

    private boolean notifOk() {
        return Build.VERSION.SDK_INT < 33 || tiene(Manifest.permission.POST_NOTIFICATIONS);
    }

    private boolean bateriaOk() {
        PowerManager pm = (PowerManager) getSystemService(POWER_SERVICE);
        return pm.isIgnoringBatteryOptimizations(getPackageName());
    }

    private boolean gpsOk() {
        LocationManager lm = (LocationManager) getSystemService(Context.LOCATION_SERVICE);
        try { return lm.isProviderEnabled(LocationManager.GPS_PROVIDER); } catch (Exception e) { return false; }
    }

    /** Pide, uno por uno, lo que falte. */
    private void siguientePermiso() {
        if (!ubicOk()) {
            requestPermissions(new String[]{Manifest.permission.ACCESS_FINE_LOCATION,
                    Manifest.permission.ACCESS_COARSE_LOCATION}, PERM_UBIC);
        } else if (!fondoOk()) {
            // En Android 11+ esto abre la pantalla donde se elige "Permitir todo el tiempo".
            requestPermissions(new String[]{Manifest.permission.ACCESS_BACKGROUND_LOCATION}, PERM_FONDO);
        } else if (!notifOk()) {
            requestPermissions(new String[]{Manifest.permission.POST_NOTIFICATIONS}, PERM_NOTIF);
        } else if (!bateriaOk()) {
            try {
                startActivity(new Intent(Settings.ACTION_REQUEST_IGNORE_BATTERY_OPTIMIZATIONS,
                        Uri.parse("package:" + getPackageName())));
            } catch (Exception e) {
                startActivity(new Intent(Settings.ACTION_IGNORE_BATTERY_OPTIMIZATION_SETTINGS));
            }
        } else if (!gpsOk()) {
            startActivity(new Intent(Settings.ACTION_LOCATION_SOURCE_SETTINGS));
        }
        Programador.iniciarSiToca(this);
    }

    @Override
    public void onRequestPermissionsResult(int code, String[] perms, int[] res) {
        super.onRequestPermissionsResult(code, perms, res);
        boolean dado = res.length > 0 && res[0] == PackageManager.PERMISSION_GRANTED;
        if (dado) siguientePermiso();
        else if (code == PERM_FONDO || code == PERM_UBIC) {
            // Si lo negó dos veces Android ya no muestra el cuadro: abrir ajustes de la app.
            if (!shouldShowRequestPermissionRationale(perms.length > 0 ? perms[0] : "")) abrirAjustesApp();
        }
        js("window.refrescar && window.refrescar()");
    }

    private void abrirAjustesApp() {
        startActivity(new Intent(Settings.ACTION_APPLICATION_DETAILS_SETTINGS,
                Uri.parse("package:" + getPackageName())));
    }

    // ------------------------------------------------------------ puente JS

    private class Puente {
        @JavascriptInterface
        public String estado() {
            try {
                Context c = MainActivity.this;
                JSONObject o = new JSONObject();
                o.put("logueado", Prefs.logueado(c));
                o.put("nombre", Prefs.nombre(c));
                o.put("servidor", Prefs.servidor(c));
                o.put("en_horario", Prefs.enHorario(c));
                o.put("hora_inicio", Prefs.horaInicio(c));
                o.put("hora_fin", Prefs.horaFin(c));
                o.put("activo", RastreoService.activo);
                o.put("gps", gpsOk());
                o.put("permiso_ubicacion", ubicOk());
                o.put("permiso_fondo", fondoOk());
                o.put("permiso_notif", notifOk());
                o.put("bateria_libre", bateriaOk());
                o.put("pendientes", Prefs.cantidadPendiente(c));
                o.put("ultimo_envio", Prefs.ultimoEnvio(c));
                o.put("version", getPackageManager().getPackageInfo(getPackageName(), 0).versionName);
                return o.toString();
            } catch (Exception e) { return "{}"; }
        }

        @JavascriptInterface
        public void login(String id, String servidor, String usuario, String pin) {
            new Thread(() -> {
                try {
                    JSONObject b = new JSONObject();
                    b.put("usuario", usuario);
                    b.put("pin", pin);
                    Prefs.cerrarSesion(MainActivity.this);
                    Red.Resp r = Red.pedir(MainActivity.this, "POST", "/api/login", b.toString(), servidor);
                    if (r.codigo == 200) {
                        JSONObject j = new JSONObject(r.cuerpo);
                        Prefs.guardarSesion(MainActivity.this, servidor, j.getString("token"), j.optString("nombre"));
                        Prefs.guardarConfig(MainActivity.this, j.optJSONObject("config"));
                        runOnUiThread(MainActivity.this::siguientePermiso);
                    }
                    responder(id, r.codigo, r.cuerpo);
                } catch (Exception e) {
                    responder(id, 0, "{\"error\":\"Respuesta inválida del servidor\"}");
                }
            }).start();
        }

        @JavascriptInterface
        public void http(String id, String metodo, String ruta, String cuerpo) {
            new Thread(() -> {
                Red.Resp r = Red.pedir(MainActivity.this, metodo, ruta, cuerpo, null);
                if (r.codigo == 401) Prefs.cerrarSesion(MainActivity.this);
                responder(id, r.codigo, r.cuerpo);
            }).start();
        }

        @JavascriptInterface
        public void salir(String id) {
            new Thread(() -> {
                Red.pedir(MainActivity.this, "POST", "/api/salir", "{}", null);
                Prefs.cerrarSesion(MainActivity.this);
                stopService(new Intent(MainActivity.this, RastreoService.class));
                Programador.programar(MainActivity.this);
                responder(id, 200, "{}");
            }).start();
        }

        @JavascriptInterface
        public void arreglar() { runOnUiThread(MainActivity.this::siguientePermiso); }

        @JavascriptInterface
        public void abrirGps() { startActivity(new Intent(Settings.ACTION_LOCATION_SOURCE_SETTINGS)); }

        @JavascriptInterface
        public void ajustesApp() { abrirAjustesApp(); }

        @JavascriptInterface
        public String ubicacion() {
            try {
                if (!ubicOk()) return "";
                LocationManager lm = (LocationManager) getSystemService(Context.LOCATION_SERVICE);
                Location g = lm.getLastKnownLocation(LocationManager.GPS_PROVIDER);
                Location n = lm.getLastKnownLocation(LocationManager.NETWORK_PROVIDER);
                Location l = g == null ? n : (n == null ? g : (g.getTime() >= n.getTime() - 120_000 ? g : n));
                if (l == null || System.currentTimeMillis() - l.getTime() > 10 * 60_000) return "";
                return l.getLatitude() + "," + l.getLongitude();
            } catch (SecurityException e) { return ""; }
        }

        @JavascriptInterface
        public void mapa(String lat, String lng, String direccion) {
            Uri u = (lat != null && !lat.isEmpty())
                    ? Uri.parse("google.navigation:q=" + lat + "," + lng)
                    : Uri.parse("geo:0,0?q=" + Uri.encode(direccion + ", Machala"));
            try { startActivity(new Intent(Intent.ACTION_VIEW, u)); }
            catch (Exception e) {
                startActivity(new Intent(Intent.ACTION_VIEW, Uri.parse("geo:" + lat + "," + lng + "?q=" + lat + "," + lng)));
            }
        }

        @JavascriptInterface
        public void llamar(String tel) {
            startActivity(new Intent(Intent.ACTION_DIAL, Uri.parse("tel:" + tel)));
        }
    }
}
