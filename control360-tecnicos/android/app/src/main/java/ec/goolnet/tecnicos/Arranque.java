package ec.goolnet.tecnicos;

import android.content.BroadcastReceiver;
import android.content.Context;
import android.content.Intent;

/** Al prender el celular (o actualizar la app) vuelve a programar el rastreo. */
public class Arranque extends BroadcastReceiver {
    @Override
    public void onReceive(Context c, Intent i) {
        if (Intent.ACTION_BOOT_COMPLETED.equals(i.getAction()) && Prefs.logueado(c) && Prefs.enHorario(c)) {
            Prefs.encolarEvento(c, "apagado", "El celular se reinició");
        }
        Programador.iniciarSiToca(c);
    }
}
