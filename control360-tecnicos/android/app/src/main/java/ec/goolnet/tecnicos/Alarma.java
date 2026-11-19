package ec.goolnet.tecnicos;

import android.content.BroadcastReceiver;
import android.content.Context;
import android.content.Intent;

public class Alarma extends BroadcastReceiver {
    @Override
    public void onReceive(Context c, Intent i) {
        Programador.iniciarSiToca(c);
    }
}
