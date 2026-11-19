package ec.goolnet.tecnicos;

import android.Manifest;
import android.app.Notification;
import android.app.NotificationChannel;
import android.app.NotificationManager;
import android.app.PendingIntent;
import android.app.Service;
import android.content.Context;
import android.content.Intent;
import android.content.pm.PackageManager;
import android.content.pm.ServiceInfo;
import android.location.Location;
import android.location.LocationListener;
import android.location.LocationManager;
import android.os.BatteryManager;
import android.os.Build;
import android.os.Bundle;
import android.os.Handler;
import android.os.HandlerThread;
import android.os.IBinder;
import android.os.Looper;
import android.os.PowerManager;

import org.json.JSONArray;
import org.json.JSONObject;

import java.util.Calendar;

/**
 * Servicio en primer plano que, en horario de trabajo, toma la ubicación cada
 * N segundos (aunque la pantalla esté apagada) y la envía a CONTROL360.
 */
public class RastreoService extends Service implements LocationListener {
    private static final int NOTIF_ID = 41;
    private static final int NOTIF_GPS = 42;
    private static final String CANAL = "rastreo";
    private static final String CANAL_ALERTA = "alertas";
    private static final long EDAD_MAX_MS = 3 * 60_000L;

    public static volatile boolean activo = false;

    private LocationManager lm;
    private Handler hilo;
    private HandlerThread ht;
    private PowerManager.WakeLock wl;
    private Location ultima;
    private long ultimoPuntoMs = 0;
    private long ultimoEnvioMs = 0;
    private boolean escuchando = false;
    private Boolean gpsAntes = null;
    private boolean enviando = false;

    @Override public IBinder onBind(Intent i) { return null; }

    @Override
    public void onCreate() {
        super.onCreate();
        lm = (LocationManager) getSystemService(Context.LOCATION_SERVICE);
        ht = new HandlerThread("rastreo");
        ht.start();
        hilo = new Handler(ht.getLooper());
        crearCanales();
    }

    @Override
    public int onStartCommand(Intent intent, int flags, int startId) {
        if (!ponerEnPrimerPlano()) { stopSelf(); return START_NOT_STICKY; }
        if (!Prefs.logueado(this) || !Prefs.enHorario(this)) {
            terminar();
            return START_NOT_STICKY;
        }
        if (!activo) {
            activo = true;
            PowerManager pm = (PowerManager) getSystemService(POWER_SERVICE);
            wl = pm.newWakeLock(PowerManager.PARTIAL_WAKE_LOCK, "tecnicos:rastreo");
            wl.setReferenceCounted(false);
            wl.acquire(11 * 3600_000L);
            escuchar();
            hilo.post(tick);
        }
        Programador.programar(this);
        return START_STICKY;
    }

    private boolean ponerEnPrimerPlano() {
        try {
            Notification n = notificacion("Rastreo activo · horario " + Prefs.horaInicio(this) + " a " + Prefs.horaFin(this));
            if (Build.VERSION.SDK_INT >= 29) startForeground(NOTIF_ID, n, ServiceInfo.FOREGROUND_SERVICE_TYPE_LOCATION);
            else startForeground(NOTIF_ID, n);
            return true;
        } catch (Exception e) {
            // Sin permiso de ubicación Android no deja iniciar el servicio.
            Prefs.encolarEvento(this, "sin_permiso", "");
            return false;
        }
    }

    private boolean tienePermiso() {
        return checkSelfPermission(Manifest.permission.ACCESS_FINE_LOCATION) == PackageManager.PERMISSION_GRANTED
                || checkSelfPermission(Manifest.permission.ACCESS_COARSE_LOCATION) == PackageManager.PERMISSION_GRANTED;
    }

    private void escuchar() {
        if (escuchando || !tienePermiso()) return;
        long ms = Prefs.intervaloSeg(this) * 1000L;
        Looper lp = ht.getLooper();
        try {
            if (lm.getAllProviders().contains(LocationManager.GPS_PROVIDER))
                lm.requestLocationUpdates(LocationManager.GPS_PROVIDER, ms, 0f, this, lp);
            if (lm.getAllProviders().contains(LocationManager.NETWORK_PROVIDER))
                lm.requestLocationUpdates(LocationManager.NETWORK_PROVIDER, ms, 0f, this, lp);
            escuchando = true;
        } catch (SecurityException ignored) {}
    }

    private void dejarDeEscuchar() {
        if (!escuchando) return;
        try { lm.removeUpdates(this); } catch (Exception ignored) {}
        escuchando = false;
    }

    // ------------------------------------------------------------ ubicación

    @Override
    public void onLocationChanged(Location l) {
        if (l == null) return;
        if (ultima == null) { ultima = l; return; }
        long edad = l.getTime() - ultima.getTime();
        boolean masPrecisa = l.getAccuracy() <= ultima.getAccuracy();
        boolean gps = LocationManager.GPS_PROVIDER.equals(l.getProvider());
        // Preferir GPS; aceptar red solo si el GPS lleva rato sin dar nada.
        if (gps || masPrecisa || edad > 60_000 || !LocationManager.GPS_PROVIDER.equals(ultima.getProvider())) {
            ultima = l;
        }
    }

    @Override public void onProviderEnabled(String p) {}
    @Override public void onProviderDisabled(String p) {}
    @Override public void onStatusChanged(String p, int s, Bundle b) {}

    // ------------------------------------------------------------ ciclo

    private final Runnable tick = new Runnable() {
        @Override public void run() {
            if (!activo) return;
            if (!Prefs.logueado(RastreoService.this) || !Prefs.enHorario(RastreoService.this)) {
                terminar();
                return;
            }
            revisarGps();
            if (!escuchando) escuchar();
            long ahora = System.currentTimeMillis();
            int seg = Prefs.intervaloSeg(RastreoService.this);
            if (ultima != null && ahora - ultima.getTime() < EDAD_MAX_MS && ahora - ultimoPuntoMs >= seg * 1000L - 2000) {
                guardarPunto(ultima, ahora);
                ultimoPuntoMs = ahora;
            }
            if (ahora - ultimoEnvioMs >= seg * 1000L) {
                ultimoEnvioMs = ahora;
                enviar();
            }
            hilo.postDelayed(this, 5000);
        }
    };

    private void guardarPunto(Location l, long ahora) {
        try {
            JSONObject p = new JSONObject();
            p.put("ts", ahora / 1000);
            p.put("lat", l.getLatitude());
            p.put("lng", l.getLongitude());
            p.put("acc", Math.round(l.getAccuracy()));
            if (l.hasSpeed()) p.put("vel", Math.round(l.getSpeed() * 3.6));
            BatteryManager bm = (BatteryManager) getSystemService(BATTERY_SERVICE);
            int bat = bm.getIntProperty(BatteryManager.BATTERY_PROPERTY_CAPACITY);
            boolean carga = bm.isCharging();
            p.put("bat", bat);
            p.put("carga", carga);
            Prefs.encolarPunto(this, p);
            revisarBateria(bat, carga);
        } catch (Exception ignored) {}
    }

    private void revisarBateria(int bat, boolean carga) {
        if (bat <= 0 || carga || bat > 15) return;
        Calendar k = Calendar.getInstance(Prefs.ZONA);
        String hoy = k.get(Calendar.YEAR) + "-" + k.get(Calendar.DAY_OF_YEAR);
        if (!hoy.equals(Prefs.sp(this).getString("aviso_bateria", ""))) {
            Prefs.sp(this).edit().putString("aviso_bateria", hoy).apply();
            Prefs.encolarEvento(this, "bateria_baja", String.valueOf(bat));
        }
    }

    private void revisarGps() {
        boolean gps;
        try { gps = lm.isProviderEnabled(LocationManager.GPS_PROVIDER); } catch (Exception e) { gps = false; }
        boolean permiso = tienePermiso();
        boolean ok = gps && permiso;
        if (gpsAntes == null || gpsAntes != ok) {
            if (gpsAntes != null || !ok) {
                if (!permiso) Prefs.encolarEvento(this, "sin_permiso", "");
                else Prefs.encolarEvento(this, ok ? "gps_encendido" : "gps_apagado", "");
            }
            gpsAntes = ok;
            NotificationManager nm = (NotificationManager) getSystemService(NOTIFICATION_SERVICE);
            if (!ok) {
                nm.notify(NOTIF_GPS, alertaGps(permiso));
                actualizarNotif("Sin ubicación: " + (permiso ? "encienda el GPS" : "dé permiso de ubicación"));
            } else {
                nm.cancel(NOTIF_GPS);
                actualizarNotif("Rastreo activo · horario " + Prefs.horaInicio(this) + " a " + Prefs.horaFin(this));
            }
        }
    }

    private void enviar() {
        if (enviando) return;
        final JSONArray[] pend = Prefs.pendientes(this);
        if (pend[0].length() == 0 && pend[1].length() == 0) return;
        enviando = true;
        new Thread(() -> {
            try {
                int n = Math.min(500, pend[0].length());
                int m = pend[1].length();
                JSONArray p = new JSONArray();
                for (int i = 0; i < n; i++) p.put(pend[0].opt(i));
                JSONObject cuerpo = new JSONObject();
                cuerpo.put("puntos", p);
                cuerpo.put("eventos", pend[1]);
                Red.Resp r = Red.pedir(this, "POST", "/api/ubicaciones", cuerpo.toString(), null);
                if (r.codigo == 200) {
                    Prefs.quitar(this, n, m);
                    try { Prefs.guardarConfig(this, new JSONObject(r.cuerpo).optJSONObject("config")); }
                    catch (Exception ignored) {}
                } else if (r.codigo == 401) {
                    // El administrador desactivó al técnico o cambió su PIN.
                    Prefs.cerrarSesion(this);
                }
            } catch (Exception ignored) {
            } finally {
                enviando = false;
            }
        }).start();
    }

    private void terminar() {
        activo = false;
        dejarDeEscuchar();
        hilo.removeCallbacks(tick);
        if (Prefs.logueado(this)) {
            // último envío antes de cerrar
            final JSONArray[] pend = Prefs.pendientes(this);
            if (pend[0].length() > 0 || pend[1].length() > 0) enviar();
        }
        ((NotificationManager) getSystemService(NOTIFICATION_SERVICE)).cancel(NOTIF_GPS);
        Programador.programar(this);
        if (wl != null && wl.isHeld()) wl.release();
        hilo.postDelayed(() -> {
            if (Build.VERSION.SDK_INT >= 24) stopForeground(STOP_FOREGROUND_REMOVE); else stopForeground(true);
            stopSelf();
        }, 8000);
    }

    @Override
    public void onDestroy() {
        activo = false;
        dejarDeEscuchar();
        if (wl != null && wl.isHeld()) wl.release();
        ht.quitSafely();
        super.onDestroy();
    }

    // ------------------------------------------------------------ notificaciones

    private void crearCanales() {
        if (Build.VERSION.SDK_INT < 26) return;
        NotificationManager nm = (NotificationManager) getSystemService(NOTIFICATION_SERVICE);
        NotificationChannel a = new NotificationChannel(CANAL, "Rastreo en horario", NotificationManager.IMPORTANCE_LOW);
        a.setShowBadge(false);
        nm.createNotificationChannel(a);
        nm.createNotificationChannel(new NotificationChannel(CANAL_ALERTA, "Avisos de GPS", NotificationManager.IMPORTANCE_HIGH));
    }

    private PendingIntent abrirApp() {
        return PendingIntent.getActivity(this, 0, new Intent(this, MainActivity.class),
                PendingIntent.FLAG_UPDATE_CURRENT | PendingIntent.FLAG_IMMUTABLE);
    }

    private Notification notificacion(String texto) {
        Notification.Builder b = Build.VERSION.SDK_INT >= 26 ? new Notification.Builder(this, CANAL) : new Notification.Builder(this);
        b.setSmallIcon(R.drawable.ic_notif)
         .setContentTitle("Técnicos Orange")
         .setContentText(texto)
         .setOngoing(true)
         .setContentIntent(abrirApp());
        return b.build();
    }

    private void actualizarNotif(String texto) {
        ((NotificationManager) getSystemService(NOTIFICATION_SERVICE)).notify(NOTIF_ID, notificacion(texto));
    }

    private Notification alertaGps(boolean permiso) {
        Notification.Builder b = Build.VERSION.SDK_INT >= 26 ? new Notification.Builder(this, CANAL_ALERTA) : new Notification.Builder(this);
        b.setSmallIcon(R.drawable.ic_notif)
         .setContentTitle(permiso ? "Encienda el GPS" : "Falta el permiso de ubicación")
         .setContentText("La oficina está viendo que su ubicación está apagada.")
         .setAutoCancel(false)
         .setContentIntent(abrirApp());
        return b.build();
    }
}
