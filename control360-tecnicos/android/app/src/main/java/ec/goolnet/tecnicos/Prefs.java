package ec.goolnet.tecnicos;

import android.content.Context;
import android.content.SharedPreferences;

import org.json.JSONArray;
import org.json.JSONException;
import org.json.JSONObject;

import java.util.Calendar;
import java.util.TimeZone;

/** Datos guardados en el celular: sesión, horario y la cola de ubicaciones por enviar. */
public final class Prefs {
    public static final String SERVIDOR_DEFECTO = "https://habita360.pythonanywhere.com/tecnicos";
    public static final TimeZone ZONA = TimeZone.getTimeZone("America/Guayaquil");
    private static final int MAX_COLA = 6000;
    private static final Object CANDADO = new Object();

    private Prefs() {}

    public static SharedPreferences sp(Context c) {
        return c.getApplicationContext().getSharedPreferences("tecnicos", Context.MODE_PRIVATE);
    }

    public static String servidor(Context c) { return sp(c).getString("servidor", SERVIDOR_DEFECTO); }
    public static String token(Context c) { return sp(c).getString("token", ""); }
    public static String nombre(Context c) { return sp(c).getString("nombre", ""); }
    public static boolean logueado(Context c) { return !token(c).isEmpty(); }

    public static void guardarSesion(Context c, String servidor, String token, String nombre) {
        sp(c).edit().putString("servidor", servidor).putString("token", token).putString("nombre", nombre).apply();
    }

    public static void cerrarSesion(Context c) {
        synchronized (CANDADO) {
            sp(c).edit().remove("token").remove("nombre").remove("cola_p").remove("cola_e").apply();
        }
    }

    public static void guardarConfig(Context c, JSONObject cfg) {
        if (cfg == null) return;
        SharedPreferences.Editor e = sp(c).edit();
        e.putString("hora_inicio", cfg.optString("hora_inicio", "08:00"));
        e.putString("hora_fin", cfg.optString("hora_fin", "18:30"));
        e.putInt("intervalo", Math.max(10, cfg.optInt("intervalo_seg", 30)));
        JSONArray d = cfg.optJSONArray("dias");
        if (d != null) e.putString("dias", d.toString());
        e.apply();
    }

    public static String horaInicio(Context c) { return sp(c).getString("hora_inicio", "08:00"); }
    public static String horaFin(Context c) { return sp(c).getString("hora_fin", "18:30"); }
    public static int intervaloSeg(Context c) { return sp(c).getInt("intervalo", 30); }

    private static boolean diaPermitido(Context c, int lunes0) {
        try {
            JSONArray d = new JSONArray(sp(c).getString("dias", "[0,1,2,3,4,5,6]"));
            for (int i = 0; i < d.length(); i++) if (d.getInt(i) == lunes0) return true;
            return false;
        } catch (JSONException ex) { return true; }
    }

    private static int minutos(String hhmm) {
        try {
            String[] p = hhmm.split(":");
            return Integer.parseInt(p[0]) * 60 + Integer.parseInt(p[1]);
        } catch (Exception ex) { return 0; }
    }

    private static int lunes0(Calendar k) { return (k.get(Calendar.DAY_OF_WEEK) + 5) % 7; }

    /** ¿Ahora mismo está dentro del horario de trabajo (hora de Ecuador)? */
    public static boolean enHorario(Context c) { return enHorario(c, System.currentTimeMillis()); }

    public static boolean enHorario(Context c, long ms) {
        Calendar k = Calendar.getInstance(ZONA);
        k.setTimeInMillis(ms);
        if (!diaPermitido(c, lunes0(k))) return false;
        int m = k.get(Calendar.HOUR_OF_DAY) * 60 + k.get(Calendar.MINUTE);
        return m >= minutos(horaInicio(c)) && m < minutos(horaFin(c));
    }

    /** Próximo momento (ms) en que empieza el horario. */
    public static long proximoInicio(Context c) {
        int ini = minutos(horaInicio(c));
        Calendar k = Calendar.getInstance(ZONA);
        long ahora = k.getTimeInMillis();
        for (int i = 0; i < 8; i++) {
            Calendar d = Calendar.getInstance(ZONA);
            d.setTimeInMillis(ahora);
            d.add(Calendar.DAY_OF_MONTH, i);
            d.set(Calendar.HOUR_OF_DAY, ini / 60);
            d.set(Calendar.MINUTE, ini % 60);
            d.set(Calendar.SECOND, 5);
            d.set(Calendar.MILLISECOND, 0);
            if (d.getTimeInMillis() > ahora && diaPermitido(c, lunes0(d))) return d.getTimeInMillis();
        }
        return ahora + 6 * 3600_000L;
    }

    // ---------------------------------------------------------------- cola

    public static void encolarPunto(Context c, JSONObject p) { encolar(c, "cola_p", p); }
    public static void encolarEvento(Context c, String tipo, String detalle) {
        try {
            JSONObject e = new JSONObject();
            e.put("ts", System.currentTimeMillis() / 1000);
            e.put("tipo", tipo);
            e.put("detalle", detalle == null ? "" : detalle);
            encolar(c, "cola_e", e);
        } catch (JSONException ignored) {}
    }

    private static void encolar(Context c, String clave, JSONObject o) {
        synchronized (CANDADO) {
            JSONArray a = leer(c, clave);
            a.put(o);
            if (a.length() > MAX_COLA) {
                JSONArray b = new JSONArray();
                for (int i = a.length() - MAX_COLA; i < a.length(); i++) b.put(a.opt(i));
                a = b;
            }
            sp(c).edit().putString(clave, a.toString()).apply();
        }
    }

    private static JSONArray leer(Context c, String clave) {
        try { return new JSONArray(sp(c).getString(clave, "[]")); }
        catch (JSONException ex) { return new JSONArray(); }
    }

    /** Copia de lo pendiente: [puntos, eventos]. */
    public static JSONArray[] pendientes(Context c) {
        synchronized (CANDADO) { return new JSONArray[]{leer(c, "cola_p"), leer(c, "cola_e")}; }
    }

    /** Quita de la cola los primeros n puntos y m eventos (los que ya se enviaron). */
    public static void quitar(Context c, int n, int m) {
        synchronized (CANDADO) {
            JSONArray p = leer(c, "cola_p"), e = leer(c, "cola_e");
            JSONArray p2 = new JSONArray(), e2 = new JSONArray();
            for (int i = n; i < p.length(); i++) p2.put(p.opt(i));
            for (int i = m; i < e.length(); i++) e2.put(e.opt(i));
            sp(c).edit().putString("cola_p", p2.toString()).putString("cola_e", e2.toString())
                    .putLong("ultimo_envio", System.currentTimeMillis()).apply();
        }
    }

    public static int cantidadPendiente(Context c) { return pendientes(c)[0].length(); }
    public static long ultimoEnvio(Context c) { return sp(c).getLong("ultimo_envio", 0); }
}
