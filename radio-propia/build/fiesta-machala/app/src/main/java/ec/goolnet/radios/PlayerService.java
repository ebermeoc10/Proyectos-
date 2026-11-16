package ec.goolnet.radios;

import android.app.Notification;
import android.app.NotificationChannel;
import android.app.NotificationManager;
import android.app.PendingIntent;
import android.app.Service;
import android.content.Intent;
import android.content.pm.ServiceInfo;
import android.os.Build;
import android.os.IBinder;
import android.os.PowerManager;

/** Mantiene viva la app mientras suena una radio con la pantalla apagada. */
public class PlayerService extends Service {
    private PowerManager.WakeLock lock;

    @Override public int onStartCommand(Intent intent, int flags, int startId) {
        String name = intent != null && intent.getStringExtra("name") != null ? intent.getStringExtra("name") : "Radio";
        NotificationManager nm = (NotificationManager) getSystemService(NOTIFICATION_SERVICE);
        Notification.Builder b;
        if (Build.VERSION.SDK_INT >= 26) {
            nm.createNotificationChannel(new NotificationChannel("radio", "Reproducción", NotificationManager.IMPORTANCE_LOW));
            b = new Notification.Builder(this, "radio");
        } else b = new Notification.Builder(this);
        int fl = Build.VERSION.SDK_INT >= 23 ? PendingIntent.FLAG_IMMUTABLE : 0;
        PendingIntent open = PendingIntent.getActivity(this, 0,
                new Intent(this, MainActivity.class).addFlags(Intent.FLAG_ACTIVITY_SINGLE_TOP), fl);
        Notification n = b.setSmallIcon(android.R.drawable.ic_media_play)
                .setContentTitle(name).setContentText("En vivo")
                .setContentIntent(open).setOngoing(true).build();
        if (Build.VERSION.SDK_INT >= 29) startForeground(1, n, ServiceInfo.FOREGROUND_SERVICE_TYPE_MEDIA_PLAYBACK);
        else startForeground(1, n);
        if (lock == null) {
            lock = ((PowerManager) getSystemService(POWER_SERVICE)).newWakeLock(PowerManager.PARTIAL_WAKE_LOCK, "radios:play");
            lock.acquire(6 * 60 * 60 * 1000L);
        }
        return START_NOT_STICKY;
    }

    @Override public void onDestroy() {
        if (lock != null && lock.isHeld()) lock.release();
        super.onDestroy();
    }

    @Override public IBinder onBind(Intent i) { return null; }
}
