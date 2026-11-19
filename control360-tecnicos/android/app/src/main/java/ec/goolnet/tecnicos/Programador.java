package ec.goolnet.tecnicos;

import android.app.AlarmManager;
import android.app.PendingIntent;
import android.content.Context;
import android.content.Intent;
import android.os.Build;

/** Despierta la app a la hora de entrada y la vigila cada 15 min durante el horario. */
public final class Programador {
    private static final long VIGILANCIA_MS = 15 * 60_000L;

    private Programador() {}

    public static void programar(Context c) {
        AlarmManager am = (AlarmManager) c.getSystemService(Context.ALARM_SERVICE);
        PendingIntent pi = PendingIntent.getBroadcast(c, 7, new Intent(c, Alarma.class),
                PendingIntent.FLAG_UPDATE_CURRENT | PendingIntent.FLAG_IMMUTABLE);
        if (!Prefs.logueado(c)) { am.cancel(pi); return; }
        long cuando = Prefs.enHorario(c)
                ? System.currentTimeMillis() + VIGILANCIA_MS
                : Prefs.proximoInicio(c);
        try {
            if (Build.VERSION.SDK_INT >= 31 && am.canScheduleExactAlarms()) {
                am.setExactAndAllowWhileIdle(AlarmManager.RTC_WAKEUP, cuando, pi);
            } else if (Build.VERSION.SDK_INT < 31) {
                am.setExactAndAllowWhileIdle(AlarmManager.RTC_WAKEUP, cuando, pi);
            } else {
                am.setAndAllowWhileIdle(AlarmManager.RTC_WAKEUP, cuando, pi);
            }
        } catch (SecurityException e) {
            am.setAndAllowWhileIdle(AlarmManager.RTC_WAKEUP, cuando, pi);
        }
    }

    /** Arranca el servicio si toca (en horario y con sesión). */
    public static void iniciarSiToca(Context c) {
        if (Prefs.logueado(c) && Prefs.enHorario(c)) {
            Intent i = new Intent(c, RastreoService.class);
            try {
                if (Build.VERSION.SDK_INT >= 26) c.startForegroundService(i); else c.startService(i);
            } catch (Exception ignored) {
                // Android no dejó arrancar desde segundo plano; se reintenta en la próxima vigilancia.
            }
        }
        programar(c);
    }
}
