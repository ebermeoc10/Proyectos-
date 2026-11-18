// Provisión por defecto para ONT Huawei (modelo de datos TR-098 /
// InternetGatewayDevice). Cárgalo en GenieACS > Admin > Provisions con
// nombre "default". Se ejecuta en cada "inform" de la ONT y refresca los
// datos que la app necesita: tabla de hosts y configuración WLAN.

const now = Date.now();

// Refresca cada 5 minutos como máximo para no saturar las ONT.
const REFRESH_MS = 300 * 1000;

// Parámetros a mantener frescos.
declare("InternetGatewayDevice.LANDevice.1.Hosts.Host.*.*", { value: now - REFRESH_MS });
declare("InternetGatewayDevice.LANDevice.1.WLANConfiguration.*.SSID", { value: now - REFRESH_MS });
declare("InternetGatewayDevice.LANDevice.1.WLANConfiguration.*.Enable", { value: now - REFRESH_MS });
declare("InternetGatewayDevice.LANDevice.1.WLANConfiguration.*.AssociatedDevice.*.*", { value: now - REFRESH_MS });

// Asegura el Periodic Inform cada 300 s.
declare("InternetGatewayDevice.ManagementServer.PeriodicInformEnable", { value: now }, { value: true });
declare("InternetGatewayDevice.ManagementServer.PeriodicInformInterval", { value: now }, { value: 300 });
