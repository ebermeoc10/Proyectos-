package ec.goolnet.tecnicos;

import android.content.Context;

import java.io.ByteArrayOutputStream;
import java.io.InputStream;
import java.io.OutputStream;
import java.net.HttpURLConnection;
import java.net.URL;
import java.nio.charset.StandardCharsets;

/** Llamadas HTTP al servidor de CONTROL360 (siempre fuera del hilo principal). */
public final class Red {
    private Red() {}

    public static final class Resp {
        public final int codigo;
        public final String cuerpo;
        Resp(int codigo, String cuerpo) { this.codigo = codigo; this.cuerpo = cuerpo; }
    }

    /** Descarga un texto público (sin enviar el token del técnico). */
    public static String texto(String url) {
        HttpURLConnection h = null;
        try {
            h = (HttpURLConnection) new URL(url).openConnection();
            h.setConnectTimeout(15000);
            h.setReadTimeout(20000);
            h.setInstanceFollowRedirects(true);
            if (h.getResponseCode() != 200) return null;
            ByteArrayOutputStream bo = new ByteArrayOutputStream();
            try (InputStream in = h.getInputStream()) {
                byte[] buf = new byte[8192];
                int n;
                while ((n = in.read(buf)) > 0) bo.write(buf, 0, n);
            }
            return bo.toString("UTF-8");
        } catch (Exception e) {
            return null;
        } finally {
            if (h != null) h.disconnect();
        }
    }

    public static Resp pedir(Context c, String metodo, String ruta, String cuerpo, String servidor) {
        HttpURLConnection h = null;
        try {
            String base = servidor != null ? servidor : Prefs.servidor(c);
            if (base.endsWith("/")) base = base.substring(0, base.length() - 1);
            h = (HttpURLConnection) new URL(base + ruta).openConnection();
            h.setConnectTimeout(15000);
            h.setReadTimeout(20000);
            h.setRequestMethod(metodo);
            h.setRequestProperty("Content-Type", "application/json; charset=utf-8");
            String tok = Prefs.token(c);
            if (!tok.isEmpty()) h.setRequestProperty("Authorization", "Bearer " + tok);
            if (cuerpo != null && !"GET".equals(metodo)) {
                h.setDoOutput(true);
                byte[] b = cuerpo.getBytes(StandardCharsets.UTF_8);
                try (OutputStream o = h.getOutputStream()) { o.write(b); }
            }
            int cod = h.getResponseCode();
            InputStream in = cod >= 400 ? h.getErrorStream() : h.getInputStream();
            String txt = "";
            if (in != null) {
                ByteArrayOutputStream bo = new ByteArrayOutputStream();
                byte[] buf = new byte[8192];
                int n;
                while ((n = in.read(buf)) > 0) bo.write(buf, 0, n);
                in.close();
                txt = bo.toString("UTF-8");
            }
            return new Resp(cod, txt);
        } catch (Exception e) {
            return new Resp(0, "{\"error\":\"Sin conexión con el servidor\"}");
        } finally {
            if (h != null) h.disconnect();
        }
    }
}
