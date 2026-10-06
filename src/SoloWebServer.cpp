/**
 * @file SoloWebServer.cpp
 * @brief SoloWebServer実装
 */

#include "SoloWebServer.h"

#include <ArduinoJson.h>

#include "ConvertPage.h"
#include "Settings.h"
#include <Wire.h>
#include <LittleFS.h>
#include <string.h>

namespace sastle {

namespace {

constexpr size_t kRxBufSize = 4096;
/// LittleFS のメタデータ/ウェアレベリング余裕。空き容量からこれを引いた分だけ受け付ける。
constexpr size_t kFsMargin = 64 * 1024;
constexpr const char* kTmpPath = "/video.tmp";
constexpr int kRecvTimeoutRetries = 5;

// ---------------------------------------------------------------------------
// 埋め込み Web UI (iPhone Safari 向け最小構成。外部リソース依存なし)
// NOTE: <input type=file> に accept を付けない。iOS は未知の拡張子 (.mjpg) を accept に含めると
//       「ファイル」アプリで該当ファイルがグレーアウトして選べなくなる。形式検証はサーバ側で行う。
// ---------------------------------------------------------------------------
const char kIndexHtml[] PROGMEM = R"HTML(<!doctype html><html lang="ja"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
<title>Isolation Sphere solo</title>
<style>
:root{color-scheme:dark}
body{font-family:-apple-system,system-ui,sans-serif;margin:0 auto;padding:16px;max-width:520px;background:#111;color:#eee}
h1{font-size:20px;margin:8px 0 16px}h1 small{color:#888;font-weight:normal}
.card{background:#1d1d1f;border-radius:12px;padding:14px;margin-bottom:14px}
.row{display:flex;justify-content:space-between;align-items:center;gap:8px;margin:6px 0}
.k{color:#999;font-size:13px}.v{font-variant-numeric:tabular-nums;text-align:right}
button{font-size:16px;padding:12px 16px;border:0;border-radius:10px;background:#2c7be5;color:#fff;flex:1}
button.warn{background:#c0392b}button.gray{background:#444}button:disabled{opacity:.4}
a.btnlink{display:block;flex:1;text-align:center;text-decoration:none;font-size:16px;font-weight:bold;padding:14px 16px;border-radius:10px;background:#2c7be5;color:#fff}
input[type=range]{width:100%}
/* ファイル選択: iOS 既定の「ファイルを選択」は小さく見づらいので、擬似要素で
   ネイティブボタンを大きくする。DOM 構造は変えない (透明な要素を重ねると
   端末によってタップが通らなくなるため)。::file-selector-button は標準名、
   ::-webkit-file-upload-button は Safari の旧名で、両方指定しておく。 */
input[type=file]{width:100%;font-size:16px;padding:10px;border:1px dashed #555;border-radius:10px;background:#111;color:#aaa;box-sizing:border-box}
input[type=file]::file-selector-button{font-size:17px;font-weight:bold;padding:14px 18px;margin-right:12px;border:0;border-radius:10px;background:#2c7be5;color:#fff}
input[type=file]::-webkit-file-upload-button{font-size:17px;font-weight:bold;padding:14px 18px;margin-right:12px;border:0;border-radius:10px;background:#2c7be5;color:#fff}
input[type=text],input[type=password]{width:100%;font-size:16px;padding:10px;margin:4px 0;border-radius:8px;border:1px solid #444;background:#111;color:#eee;box-sizing:border-box}
select{font-size:16px;padding:8px;border-radius:8px;border:1px solid #444;background:#111;color:#eee}
progress{width:100%;height:14px}
.st{display:inline-block;padding:2px 10px;border-radius:999px;font-size:13px;background:#333}
.st.playing{background:#1e8449}.st.paused{background:#7d6608}.st.error{background:#c0392b}.st.uploading{background:#d68910}
small{color:#888}#msg{min-height:1.2em;color:#f5b041;font-size:14px;word-break:break-all}
</style></head><body>
<h1 id="deviceName">Isolation Sphere <small>solo</small></h1>
<div id="cna" class="card" hidden style="background:#3b2f00"><b>接続できました。</b><br><small>この「ログイン」画面ではファイル選択ができない場合があります。動画をアップロードするときは、この画面を閉じてから Safari で <b id="cnaUrl">http://192.168.4.1/</b> を開いてください。再生・停止・明るさはここから操作できます。</small></div>
<div class="card">
 <div class="row"><span class="k">状態</span><span id="state" class="st">-</span></div>
 <div class="row"><span class="k">動画</span><span id="video" class="v">-</span></div>
 <div class="row"><span class="k">再生</span><span id="stats" class="v">-</span></div>
 <div class="row"><span class="k">空き容量</span><span id="fs" class="v">-</span></div>
 <div id="msg"></div>
 <div class="row"><button id="play">再生</button><button id="pause" class="gray">一時停止</button><button id="stop" class="gray">停止</button></div>
 <small>一時停止は現在のフレームを表示したまま止まり、停止は消灯します。どちらも再生で続きから再開します。</small>
</div>
<div class="card">
 <div class="row"><span class="k">明るさ</span><span id="bval" class="v">-</span></div>
 <input id="bri" type="range" min="0" max="100" step="1">
</div>
<div class="card">
 <div class="k">動画の入れ替え</div>
 <p><small>下のボタンから専用ページを開きます。iPhone で撮った動画をその場で 320×160 / 10fps に変換して、そのまま投入できます (変換済みの .mjpg もそのページから入れられます)。ファイルを選ぶのは 1 回だけです。</small></p>
 <p><small>アップロード中は再生が止まり、成功すると新しい動画を先頭から再生します。空き容量が足りない場合は現在の動画を先に削除してから受信します (失敗すると「動画なし」になり再アップロードできます)。</small></p>
 <div class="row"><a id="conv" class="btnlink" href="/convert">動画を選ぶ (変換してアップロード)</a></div>
 <div class="row"><button id="del" class="warn">保存済み動画を削除</button></div>
</div>
<div class="card">
 <div class="k">IMU (姿勢センサー)</div>
 <div class="row"><span class="k">状態</span><span id="i_st" class="v">-</span></div>
 <div class="row"><span class="k">quaternion</span><span id="i_q" class="v">-</span></div>
 <div class="row"><span class="k">読み出し</span><span id="i_rd" class="v">-</span></div>
 <div class="row"><span class="k">平滑 (フレーム)</span><span id="i_smv" class="v">-</span></div>
 <input id="i_sm" type="range" min="1" max="50" step="1">
 <div class="row"><button id="i_reset" class="gray">IMU を再初期化</button></div>
 <p><small>cal は BNO055 のキャリブレーション (sys/gyro/accel/mag、各 0-3)。fail = I2C 失敗、disc = 化け値の破棄、partial = 上位バイト欠落を検出して読み直した回数、straddle = 融合更新をまたいだ読みを検出した回数。これらが増えるのは<b>正常に検出できている</b>証拠で、姿勢に出なければ問題ありません。平滑は移動平均のフレーム数 (1 = なし。大きいほど滑らかだが遅れる)。</small></p>
</div>
<div class="card">
 <div class="k">表示パターン (配線・向きの確認用)</div>
 <div class="row"><button id="m_sphere">映像</button><button id="m_test" class="gray">テストパターン</button></div>
 <div class="row"><button id="p_strip" class="gray">ストリップ識別色</button><button id="p_chase" class="gray">チェイス</button></div>
 <div class="row"><span class="k">チェイス幅</span><span id="wval" class="v">-</span></div>
 <input id="w" type="range" min="1" max="20" step="1">
 <div class="row"><button id="axis" class="gray">XYZ軸を重ねる</button></div>
 <p><small>ストリップ識別色は 5 本の配線の同定と全点灯確認、チェイスは LED の並び順と向きの確認に使います。XYZ軸は映像に重ねて表示し、IMU が有効なら球体を回しても軸は空間に固定されて見えます (±X=赤 / ±Y=緑 / ±Z=青、マイナス側は暗色)。</small></p>
</div>
<div class="card">
 <div class="k">LAN 接続 (開発用 / 任意)</div>
 <p><small>普段の Wi-Fi にも同時接続します。PC の Wi-Fi を切り替えずに OTA 書き込みができるようになります。SSID を空で保存すると無効化します。反映は再起動後です。</small></p>
 <input id="ssid" type="text" placeholder="SSID" autocapitalize="off" autocorrect="off" spellcheck="false">
 <input id="pass" type="password" placeholder="パスワード" autocapitalize="off" autocorrect="off" spellcheck="false">
 <div class="row"><button id="wifi">保存</button></div>
</div>
<div class="card">
 <div class="k">映像ソース</div>
 <div class="row"><span class="k">表示中</span><span id="src" class="v">-</span></div>
 <div class="row"><button id="s_auto">自動</button><button id="s_local" class="gray">本体のみ</button><button id="s_net" class="gray">配信のみ</button></div>
 <p><small>自動: 配信 (UDP) が届いていればそれを表示し、途切れると本体の動画に戻ります。本体のみ: 配信を無視します。配信のみ: 本体の動画を再生しません。再起動で「自動」に戻ります。</small></p>
</div>
<div class="card">
 <div class="k">サーバ接続 (映像配信サーバがある環境向け)</div>
 <div class="row"><span class="k">状態</span><span id="srv" class="v">-</span></div>
 <p><small>ON にすると起動時に配信サーバの Wi-Fi (P2P 網) にも接続し、UDP で届く映像を優先して表示、MQTT で操作を受けます。映像が届かない間は本体の動画を再生します。OFF は本体だけで動作します。切り替えは保存して再起動します (この AP と本体の動画はどちらでも使えます)。</small></p>
 <div class="row"><button id="srv_on">ON にして再起動</button><button id="srv_off" class="gray">OFF にして再起動</button></div>
</div>
<div class="card">
 <div class="k">省電力</div>
 <div class="row"><span class="k">AP 自動停止</span>
  <select id="ap_idle"><option value="0">しない</option><option value="5">5 分</option><option value="10">10 分</option><option value="30">30 分</option><option value="60">60 分</option></select></div>
 <div class="row"><span class="k">AP (Wi-Fi)</span><span id="ap_st" class="v">-</span><button id="ap_off" class="gray">今すぐ停止</button></div>
 <div class="row"><span class="k">モデム省電力</span><button id="ms_on" class="gray">ON</button><button id="ms_off">OFF</button></div>
 <p><small>AP は接続端末が 0 台のまま設定時間が経つと止まり、LAN 接続が無ければ無線ごと停止して電力を大きく減らします。再開はトリプルシェイク、電源の入れ直し、シリアル/MQTT です。映像の再生は AP が止まっても続きます。モデム省電力は LAN (STA) 接続中のみ効き、ON だと応答が鈍り UDP 映像を取りこぼすことがあります。</small></p>
</div>
<div class="card">
 <div class="row"><span class="k">デバイス</span><span id="dev" class="v">-</span></div>
 <div class="row"><span class="k">LAN (STA)</span><span id="sta" class="v">-</span></div>
 <div class="row"><button id="reboot" class="gray">再起動</button></div>
</div>
<script>
const $=id=>document.getElementById(id);
const fmt=n=>n>=1048576?(n/1048576).toFixed(2)+' MB':n>=1024?(n/1024).toFixed(1)+' KB':n+' B';
let busy=false,briTimer=null,wTimer=null,smTimer=null,ledAxis=false;
async function api(p,body){const r=await fetch(p,{method:'POST',headers:{'Content-Type':'application/json'},body:body?JSON.stringify(body):'{}'});const j=await r.json().catch(()=>({}));if(!r.ok)throw new Error(j.error||('HTTP '+r.status));return j}
const say=t=>{$('msg').textContent=t};
async function refresh(){if(busy)return;try{const r=await fetch('/api/status',{cache:'no-store'});const s=await r.json();
 const st=$('state');st.textContent=s.state+(s.error?' - '+s.error:'');st.className='st '+s.state;
 $('video').textContent=s.video.present?`${s.video.frames}f / ${s.video.duration_s.toFixed(1)}s / ${fmt(s.video.bytes)}`:'なし';
 $('stats').textContent=`${s.stats.fps.toFixed(1)} fps / miss ${s.stats.deadline_misses} / err ${s.stats.decode_errors}`;
 $('fs').textContent=`${fmt(s.fs.free)} (最大 ${fmt(s.fs.max_upload)})`;
 if(document.activeElement!==$('bri')){$('bri').value=s.brightness;$('bval').textContent=s.brightness+'%'}
 $('dev').textContent=`${s.device} / AP ${s.ap.ssid} (${s.ap.clients}) / up ${s.uptime_s}s`;
 $('deviceName').textContent=s.ap.ssid;document.title=s.ap.ssid;
 if(s.imu){const I=s.imu;
  $('i_st').textContent=I.ok?`OK mode=${I.mode} cal=${I.cal}`:'無効 (未検出)';
  $('i_q').textContent=I.quat.map(x=>x.toFixed(3)).join(' ');
  $('i_rd').textContent=`${I.reads} / fail ${I.fails} / disc ${I.discards} / partial ${I.partial} / straddle ${I.straddle}`;
  if(document.activeElement!==$('i_sm')){$('i_sm').value=I.smooth;$('i_smv').textContent=I.smooth}}
 if(s.led){const L=s.led;ledAxis=L.axis;
  const sel=(id,on)=>$(id).className=on?'':'gray';
  sel('m_sphere',L.mode==='sphere');sel('m_test',L.mode==='test');
  sel('p_strip',L.pattern==='strip');sel('p_chase',L.pattern==='chase');
  sel('axis',L.axis);$('axis').textContent=L.axis?'XYZ軸を重ねる (ON)':'XYZ軸を重ねる';
  if(document.activeElement!==$('w')){$('w').value=L.width;$('wval').textContent=L.width}}
 if(s.power){const P=s.power;
  const sel=(id,on)=>$(id).className=on?'':'gray';
  sel('ms_on',P.modem_sleep);sel('ms_off',!P.modem_sleep);
  $('ap_st').textContent=P.ap_running?'動作中':'停止中';
  if(document.activeElement!==$('ap_idle')){if(![...$('ap_idle').options].some(o=>+o.value===P.ap_idle_min))$('ap_idle').add(new Option(P.ap_idle_min+' 分',P.ap_idle_min));$('ap_idle').value=P.ap_idle_min}}
 if(s.sta){$('sta').textContent=!s.sta.enabled?'未設定':(s.sta.connected?`${s.sta.ssid} ${s.sta.ip} (${s.sta.origin})`:`${s.sta.ssid} 接続中… (${s.sta.origin})`);
  if(document.activeElement!==$('ssid')&&!$('ssid').value&&s.sta.origin==='nvs'&&s.sta.ssid)$('ssid').placeholder=s.sta.ssid}
 if(s.source){const R=s.source;const an={local:'本体の動画',network:'配信 (UDP)',none:'なし'}[R.active]||R.active;
  $('src').textContent=`${an} / ${R.net_fps.toFixed(1)} fps 受信 (${R.net_frames} 枚, 欠落 ${R.reasm_drop})`;
  const sel=(id,on)=>$(id).className=on?'':'gray';sel('s_auto',R.mode==='auto');sel('s_local',R.mode==='local');sel('s_net',R.mode==='network')}
 if(s.server){const S=s.server;$('srv').textContent=S.enabled&&S.ssid?`ON: ${S.ssid} / ${S.broker} (MQTT ${S.mqtt?'接続中':'未接続'})`:'OFF (本体のみ)';
  $('srv_on').className=S.enabled?'':'gray';$('srv_off').className=S.enabled?'gray':''}
 $('play').disabled=!(s.state==='stopped'||s.state==='paused');$('pause').disabled=s.state!=='playing';$('stop').disabled=!(s.state==='playing'||s.state==='paused');
 $('del').disabled=!s.video.present||s.state==='uploading';
 $('conv').style.opacity=s.state==='uploading'?.4:1;
}catch(e){$('state').textContent='接続エラー';$('state').className='st error'}}
$('play').onclick=()=>api('/api/play').then(refresh).catch(e=>say(e.message));
$('stop').onclick=()=>api('/api/stop').then(refresh).catch(e=>say(e.message));
$('pause').onclick=()=>api('/api/pause').then(refresh).catch(e=>say(e.message));
$('bri').oninput=e=>{$('bval').textContent=e.target.value+'%';clearTimeout(briTimer);briTimer=setTimeout(()=>api('/api/brightness',{value:+e.target.value}).catch(e=>say(e.message)),150)};
const led=b=>api('/api/led',b).then(refresh).catch(e=>say(e.message));
$('m_sphere').onclick=()=>led({mode:'sphere'});
$('m_test').onclick=()=>led({mode:'test'});
$('p_strip').onclick=()=>led({pattern:'strip'});
$('p_chase').onclick=()=>led({pattern:'chase'});
$('axis').onclick=()=>led({axis:!ledAxis});
$('w').oninput=e=>{$('wval').textContent=e.target.value;clearTimeout(wTimer);wTimer=setTimeout(()=>led({width:+e.target.value}),250)};
$('del').onclick=()=>{if(confirm('保存済み動画を削除しますか？'))api('/api/video/delete').then(refresh).catch(e=>say(e.message))};
$('reboot').onclick=()=>{if(confirm('再起動しますか？'))api('/api/reboot').then(()=>say('再起動中…')).catch(e=>say(e.message))};
const srv=on=>{if(confirm(`サーバ接続を ${on?'ON':'OFF'} にして再起動しますか？`))api('/api/server',{enabled:on}).then(()=>say('保存しました。再起動中…')).catch(e=>say(e.message))};
$('srv_on').onclick=()=>srv(true);$('srv_off').onclick=()=>srv(false);
const pwr=b=>api('/api/power',b).then(refresh).catch(e=>say(e.message));
$('ms_on').onclick=()=>pwr({modem_sleep:true});$('ms_off').onclick=()=>pwr({modem_sleep:false});
$('ap_idle').onchange=e=>pwr({ap_idle_min:+e.target.value});
$('ap_off').onclick=()=>{if(confirm('AP を停止します。この画面との接続も切れます。再開はトリプルシェイクか電源の入れ直しです。'))api('/api/power',{ap:false}).then(()=>say('AP を停止します…')).catch(e=>say(e.message))};
const src=m=>api('/api/source',{mode:m}).then(refresh).catch(e=>say(e.message));
$('s_auto').onclick=()=>src('auto');$('s_local').onclick=()=>src('local');$('s_net').onclick=()=>src('network');
$('i_sm').oninput=e=>{$('i_smv').textContent=e.target.value;clearTimeout(smTimer);smTimer=setTimeout(()=>api('/api/imu',{smooth_frames:+e.target.value}).then(refresh).catch(e=>say(e.message)),250)};
$('i_reset').onclick=()=>{if(confirm('IMU (BNO055) を再初期化しますか？'))api('/api/imu',{reset:true}).then(()=>say('IMU を再初期化しました')).catch(e=>say(e.message))};
$('wifi').onclick=()=>{const sd=$('ssid').value.trim();
 if(!sd&&!confirm('SSID が空です。LAN 接続を無効にしますか？'))return;
 api('/api/wifi',{ssid:sd,password:$('pass').value}).then(j=>{$('pass').value='';say(sd?`保存しました (${j.ssid})。再起動後に接続します`:'LAN 接続を無効にしました')}).catch(e=>say(e.message))};

if(/[?&]cna=1/.test(location.search)){$('cna').hidden=false;$('cnaUrl').textContent=location.origin+'/'}
refresh();setInterval(refresh,2000);
</script></body></html>)HTML";

}  // namespace

// ---------------------------------------------------------------------------

SoloWebServer::SoloWebServer()
    : _server(nullptr),
      _ctl(nullptr),
      _config(nullptr),
      _player(nullptr),
      _led(nullptr),
      _net(nullptr),
      _imu(nullptr),
      _rxBuf(nullptr),
      _uploads(0),
      _uploadFailures(0) {
    _jsonBuf[0] = '\0';
}

SoloWebServer::~SoloWebServer() {
    end();
    if (_rxBuf) {
        free(_rxBuf);
        _rxBuf = nullptr;
    }
}

bool SoloWebServer::begin(DeviceController& ctl, ConfigManager& config, SoloPlayer& player,
                          LEDManager& led, NetworkManager& net, IMUManager& imu, uint16_t port,
                          UdpReceiver* udp) {
    if (_server) {
        return true;
    }
    _ctl = &ctl;
    _udp = udp;
    _config = &config;
    _player = &player;
    _led = &led;
    _net = &net;
    _imu = &imu;

    if (!_rxBuf) {
        _rxBuf = (uint8_t*)malloc(kRxBufSize);
        if (!_rxBuf) {
            Serial.println("[SoloWeb] ERROR: rx buffer allocation failed");
            return false;
        }
    }

    httpd_config_t cfg = HTTPD_DEFAULT_CONFIG();
    cfg.server_port = port;
    cfg.core_id = 0;               // WiFi/lwIP・再生タスクと同じ Core0。描画(Core1)を汚さない
    cfg.task_priority = 1;         // 既定(5)は高すぎる。デコード (frame_pump, prio 2) より下に置き、
                                   // 状態表示やアップロード受信が再生の締切を奪わないようにする
    cfg.stack_size = 8192;
    cfg.max_uri_handlers = 20;
    cfg.max_open_sockets = 4;
    cfg.lru_purge_enable = true;
    cfg.recv_wait_timeout = 30;
    cfg.send_wait_timeout = 30;

    if (httpd_start(&_server, &cfg) != ESP_OK) {
        Serial.println("[SoloWeb] ERROR: httpd_start failed");
        _server = nullptr;
        return false;
    }

    const httpd_uri_t routes[] = {
        {"/",                 HTTP_GET,  onRoot,       this, false, false, nullptr},
        {"/convert",          HTTP_GET,  onConvert,    this, false, false, nullptr},
        {"/api/status",       HTTP_GET,  onStatus,     this, false, false, nullptr},
        {"/api/play",         HTTP_POST, onPlay,       this, false, false, nullptr},
        {"/api/stop",         HTTP_POST, onStop,       this, false, false, nullptr},
        {"/api/pause",        HTTP_POST, onPause,      this, false, false, nullptr},
        {"/api/wifi",         HTTP_POST, onWifi,       this, false, false, nullptr},
        {"/api/led",          HTTP_POST, onLed,        this, false, false, nullptr},
        {"/api/imu",          HTTP_GET,  onImuGet,     this, false, false, nullptr},
        {"/api/imu",          HTTP_POST, onImuPost,    this, false, false, nullptr},
        {"/api/server",       HTTP_POST, onServer,     this, false, false, nullptr},
        {"/api/power",        HTTP_POST, onPower,      this, false, false, nullptr},
        {"/api/source",       HTTP_POST, onSource,     this, false, false, nullptr},
        {"/api/brightness",   HTTP_POST, onBrightness, this, false, false, nullptr},
        {"/api/video",        HTTP_POST, onUpload,     this, false, false, nullptr},
        {"/api/video/delete", HTTP_POST, onDelete,     this, false, false, nullptr},
        {"/api/reboot",       HTTP_POST, onReboot,     this, false, false, nullptr},
    };
    for (const auto& r : routes) {
        if (httpd_register_uri_handler(_server, &r) != ESP_OK) {
            Serial.printf("[SoloWeb] ERROR: failed to register %s\n", r.uri);
        }
    }
    httpd_register_err_handler(_server, HTTPD_404_NOT_FOUND, onNotFound);
    refreshFsUsage();

    // キャプティブポータル用 DNS (全ホスト名 → AP の IP)
    _dns.setTTL(60);
    _dns.setErrorReplyCode(DNSReplyCode::NoError);
    _dnsStarted = _dns.start(53, "*", WiFi.softAPIP());
    if (!_dnsStarted) {
        Serial.println("[SoloWeb] WARN: captive DNS failed to start (UI still reachable by IP)");
    }

    Serial.printf("[SoloWeb] HTTP server listening on port %u (captive portal %s)\n",
                  (unsigned)port, _dnsStarted ? "on" : "off");
    return true;
}

void SoloWebServer::end() {
    if (_dnsStarted) {
        _dns.stop();
        _dnsStarted = false;
    }
    if (_server) {
        httpd_stop(_server);
        _server = nullptr;
    }
}

void SoloWebServer::loop() {
    if (_dnsStarted) {
        _dns.processNextRequest();
    }
}

// ---------------------------------------------------------------------------
// 共通ヘルパ
// ---------------------------------------------------------------------------

esp_err_t SoloWebServer::sendJson(httpd_req_t* req, const char* status, const char* json) {
    httpd_resp_set_status(req, status);
    httpd_resp_set_type(req, "application/json");
    httpd_resp_set_hdr(req, "Cache-Control", "no-store");
    return httpd_resp_send(req, json, HTTPD_RESP_USE_STRLEN);
}

esp_err_t SoloWebServer::sendError(httpd_req_t* req, const char* status, const char* message) {
    snprintf(_jsonBuf, sizeof(_jsonBuf), "{\"ok\":false,\"error\":\"%s\"}", message ? message : "error");
    return sendJson(req, status, _jsonBuf);
}

bool SoloWebServer::readBody(httpd_req_t* req, char* out, size_t cap, size_t& len) {
    len = 0;
    if (req->content_len >= cap) {
        return false;
    }
    while (len < req->content_len) {
        int r = httpd_req_recv(req, out + len, req->content_len - len);
        if (r == HTTPD_SOCK_ERR_TIMEOUT) {
            continue;
        }
        if (r <= 0) {
            return false;
        }
        len += (size_t)r;
    }
    out[len] = '\0';
    return true;
}

void SoloWebServer::refreshFsUsage() {
    _fsTotal = LittleFS.totalBytes();
    _fsUsed = LittleFS.usedBytes();
}

size_t SoloWebServer::maxUploadBytes(size_t& freeOut, size_t& existingOut) const {
    freeOut = (_fsTotal > _fsUsed) ? _fsTotal - _fsUsed : 0;
    // 既存動画のサイズは player が open 時に把握している (ファイルを開き直さない)
    existingOut = _player ? _player->videoBytes() : 0;
    // 既存動画は置換時に先に消せるので上限に含める
    const size_t avail = freeOut + existingOut;
    return (avail > kFsMargin) ? avail - kFsMargin : 0;
}

// ---------------------------------------------------------------------------
// ハンドラ
// ---------------------------------------------------------------------------

esp_err_t SoloWebServer::onRoot(httpd_req_t* req) {
    httpd_resp_set_type(req, "text/html; charset=utf-8");
    httpd_resp_set_hdr(req, "Cache-Control", "no-store");
    return httpd_resp_send(req, kIndexHtml, sizeof(kIndexHtml) - 1);
}

esp_err_t SoloWebServer::onConvert(httpd_req_t* req) {
    httpd_resp_set_type(req, "text/html; charset=utf-8");
    httpd_resp_set_hdr(req, "Cache-Control", "no-store");
    return httpd_resp_send(req, kConvertHtml, strlen(kConvertHtml));
}

esp_err_t SoloWebServer::onStatus(httpd_req_t* req) {
    auto* self = static_cast<SoloWebServer*>(req->user_ctx);
    SoloPlayer& p = *self->_player;
    const SoloPlayer::Stats st = p.stats();

    size_t fsFree = 0, existing = 0;
    const size_t maxUpload = self->maxUploadBytes(fsFree, existing);
    const char* err = p.lastError();

    // IMU 診断: 姿勢追従が止まる/化ける問題の切り分け用。シリアルが使えない
    // (組み立て後は USB 給電で再生すると電源が落ちる) ため UI から見えるようにする。
    bool imuOk = false;
    uint8_t imuMode = 0, calSys = 0, calGyro = 0, calAccel = 0, calMag = 0;
    float iqw = 0.0f, iqx = 0.0f, iqy = 0.0f, iqz = 0.0f;
    if (self->_imu && self->_imu->isInitialized()) {
        imuOk = self->_imu->getQuaternion(iqw, iqx, iqy, iqz);
        imuMode = self->_imu->getOperationMode();
        self->_imu->getCalibration(calSys, calGyro, calAccel, calMag);
    }

    // 描画 (LED) とデコードの統計。カクつきの切り分け用: out_us が LED 出力 1 回の所要時間で、
    // その間はフラッシュ操作ロックが握られ LittleFS 読み出しが待たされる
    const LEDStats ls = self->_led->getStats();
    ImageStats is = {};
    if (self->_ctl->image()) {
        is = self->_ctl->image()->getStats();
    }
    // 映像ソース (FramePump) の統計。pump が無ければゼロ
    FramePump::Stats ps = {};
    uint32_t udpRx = 0, udpDrop = 0;
    bool udpListening = false;
    if (FramePump* pump = self->_ctl->pump()) {
        ps = pump->stats();
    }
    if (self->_udp) {
        udpRx = self->_udp->received();
        udpDrop = self->_udp->dropped();
        udpListening = self->_udp->listening();
    }

    // error は静的ASCII文字列のみ (エスケープ不要)
    int n = snprintf(self->_jsonBuf, sizeof(self->_jsonBuf),
        "{\"device\":\"%s\",\"state\":\"%s\",\"error\":%s%s%s,"
        "\"video\":{\"present\":%s,\"path\":\"%s\",\"bytes\":%u,\"frames\":%u,\"duration_s\":%.1f,"
        "\"width\":%u,\"height\":%u,\"max_frame_bytes\":%u,\"in_psram\":%s,\"load_ms\":%u},"
        "\"brightness\":%u,\"fps_target\":%u,"
        "\"stats\":{\"fps\":%.2f,\"frames\":%u,\"loops\":%u,\"deadline_misses\":%u,\"decode_errors\":%u,"
        "\"last_frame_bytes\":%u,\"read_us\":%u,\"tick_us\":%u},"
        "\"fs\":{\"total\":%u,\"used\":%u,\"free\":%u,\"max_upload\":%u},"
        "\"ap\":{\"ssid\":\"%s\",\"ip\":\"%s\",\"clients\":%u},"
        "\"sta\":{\"enabled\":%s,\"connected\":%s,\"ssid\":\"%s\",\"ip\":\"%s\",\"origin\":\"%s\"},"
        "\"server\":{\"configured\":%s,\"enabled\":%s,\"ssid\":\"%s\",\"broker\":\"%s\",\"mqtt\":%s},"
        "\"source\":{\"mode\":\"%s\",\"active\":\"%s\",\"net_frames\":%u,\"net_fps\":%.1f,\"net_errors\":%u,"
        "\"udp_rx\":%u,\"udp_drop\":%u,\"reasm_drop\":%u,\"last_net_ms\":%u,\"udp_listening\":%s},"
        "\"led\":{\"mode\":\"%s\",\"pattern\":\"%s\",\"width\":%u,\"axis\":%s},"
        "\"power\":{\"ap_running\":%s,\"ap_idle_min\":%u,\"modem_sleep\":%s},"
        "\"imu\":{\"ok\":%s,\"mode\":%u,\"cal\":\"%u%u%u%u\","
        "\"quat\":[%.3f,%.3f,%.3f,%.3f],\"reads\":%u,\"fails\":%u,\"discards\":%u,\"partial\":%u,\"straddle\":%u,\"seq\":%u,\"smooth\":%u},"
        "\"render\":{\"fps\":%.1f,\"frames\":%u,\"map_us\":%u,\"out_us\":%u,\"stale\":%u},"
        "\"img\":{\"fps\":%.1f,\"decoded\":%u,\"decode_us\":%u,\"dropped\":%u,\"errors\":%u},"
        "\"uploads\":%u,\"upload_failures\":%u,"
        "\"uptime_s\":%lu,\"heap_free\":%u,\"psram_free\":%u}",
        self->_config->getSphereID().c_str(), p.stateName(),
        err ? "\"" : "null", err ? err : "", err ? "\"" : "",
        p.hasVideo() ? "true" : "false", p.videoPath().c_str(), (unsigned)p.videoBytes(),
        (unsigned)p.videoFrames(), (float)p.videoFrames() / (float)kSoloFps,
        (unsigned)p.width(), (unsigned)p.height(), (unsigned)p.maxFrameBytes(),
        p.playsFromMemory() ? "true" : "false", (unsigned)p.loadMs(),
        (unsigned)self->_ctl->brightnessPct(), (unsigned)kSoloFps,
        st.fps, (unsigned)st.frames, (unsigned)st.loops, (unsigned)st.deadlineMisses,
        (unsigned)st.decodeErrors, (unsigned)st.lastFrameBytes, (unsigned)st.lastReadUs,
        (unsigned)st.lastTickUs,
        (unsigned)self->_fsTotal, (unsigned)self->_fsUsed, (unsigned)fsFree,
        (unsigned)maxUpload,
        WiFi.softAPSSID().c_str(), WiFi.softAPIP().toString().c_str(),
        (unsigned)WiFi.softAPgetStationNum(),
        self->_net && self->_net->staEnabled() ? "true" : "false",
        self->_net && self->_net->staConnected() ? "true" : "false",
        self->_net ? self->_net->staSsid().c_str() : "",
        self->_net && self->_net->staConnected() ? WiFi.localIP().toString().c_str() : "",
        self->_net ? self->_net->staOriginName() : "none",
        self->_ctl->serverConfigured() ? "true" : "false",
        self->_config->getWiFiConfig().enabled ? "true" : "false",
        self->_config->getWiFiSSID().c_str(), self->_config->getMQTTBroker().c_str(),
        self->_ctl->mqttConnected() ? "true" : "false",
        self->_ctl->sourceModeName(), self->_ctl->activeSourceName(),
        (unsigned)ps.netFrames, ps.netFps, (unsigned)ps.netDecodeErrors,
        (unsigned)udpRx, (unsigned)udpDrop, (unsigned)ps.reasmDropped,
        (unsigned)(ps.lastNetMs ? (millis() - ps.lastNetMs) : 0), udpListening ? "true" : "false",
        self->_ctl->ledModeName(), self->_ctl->testPatternName(), (unsigned)self->_ctl->testWidth(),
        self->_ctl->axisIndicator() ? "true" : "false",
        self->_ctl->apRunning() ? "true" : "false", (unsigned)self->_ctl->apIdleMinutes(),
        self->_ctl->modemSleep() ? "true" : "false",
        imuOk ? "true" : "false", (unsigned)imuMode,
        (unsigned)calSys, (unsigned)calGyro, (unsigned)calAccel, (unsigned)calMag,
        iqw, iqx, iqy, iqz,
        (unsigned)(self->_imu ? self->_imu->debugReadTotal() : 0),
        (unsigned)(self->_imu ? self->_imu->debugReadFails() : 0),
        (unsigned)(self->_imu ? self->_imu->debugDiscards() : 0),
        (unsigned)(self->_imu ? self->_imu->debugPartialReads() : 0),
        (unsigned)(self->_imu ? self->_imu->debugStraddles() : 0),
        (unsigned)(self->_imu ? self->_imu->quatSeq() : 0),
        (unsigned)(self->_imu ? self->_imu->smoothFrames() : 0),
        ls.fps, (unsigned)ls.frames_rendered, (unsigned)ls.mapping_time_us, (unsigned)ls.output_time_us,
        (unsigned)ls.imu_stale_frames,
        is.fps, (unsigned)is.frames_decoded, (unsigned)is.decode_time_us, (unsigned)is.frames_dropped,
        (unsigned)is.decode_errors,
        (unsigned)self->_uploads, (unsigned)self->_uploadFailures,
        (unsigned long)(millis() / 1000), (unsigned)ESP.getFreeHeap(), (unsigned)ESP.getFreePsram());
    if (n < 0 || (size_t)n >= sizeof(self->_jsonBuf)) {
        return self->sendError(req, "500 Internal Server Error", "status too large");
    }
    return self->sendJson(req, "200 OK", self->_jsonBuf);
}

// 再生系 3 本の共通応答: 409 は「アップロード中」「動画なし」
static esp_err_t replyPlayResult(SoloWebServer* self, httpd_req_t* req, DeviceController::PlayResult r,
                                 char* buf, size_t cap, const char* stateName,
                                 esp_err_t (SoloWebServer::*sendJsonFn)(httpd_req_t*, const char*, const char*),
                                 esp_err_t (SoloWebServer::*sendErrorFn)(httpd_req_t*, const char*, const char*)) {
    if (r != DeviceController::PlayResult::Ok) {
        return (self->*sendErrorFn)(req, "409 Conflict", DeviceController::playResultMessage(r));
    }
    snprintf(buf, cap, "{\"ok\":true,\"state\":\"%s\"}", stateName);
    return (self->*sendJsonFn)(req, "200 OK", buf);
}

esp_err_t SoloWebServer::onPlay(httpd_req_t* req) {
    auto* self = static_cast<SoloWebServer*>(req->user_ctx);
    return replyPlayResult(self, req, self->_ctl->play(), self->_jsonBuf, sizeof(self->_jsonBuf),
                           self->_player->stateName(), &SoloWebServer::sendJson, &SoloWebServer::sendError);
}

esp_err_t SoloWebServer::onStop(httpd_req_t* req) {
    auto* self = static_cast<SoloWebServer*>(req->user_ctx);
    return replyPlayResult(self, req, self->_ctl->stop(), self->_jsonBuf, sizeof(self->_jsonBuf),
                           self->_player->stateName(), &SoloWebServer::sendJson, &SoloWebServer::sendError);
}

esp_err_t SoloWebServer::onPause(httpd_req_t* req) {
    auto* self = static_cast<SoloWebServer*>(req->user_ctx);
    return replyPlayResult(self, req, self->_ctl->pause(), self->_jsonBuf, sizeof(self->_jsonBuf),
                           self->_player->stateName(), &SoloWebServer::sendJson, &SoloWebServer::sendError);
}

// 映像ソースの調停モード: {"mode":"auto|local|network"} (再起動不要、config には保存しない)
esp_err_t SoloWebServer::onSource(httpd_req_t* req) {
    auto* self = static_cast<SoloWebServer*>(req->user_ctx);
    char body[96];
    size_t len = 0;
    if (!self->readBody(req, body, sizeof(body), len)) {
        return self->sendError(req, "400 Bad Request", "invalid body");
    }
    StaticJsonDocument<128> doc;
    if (deserializeJson(doc, body, len) != DeserializationError::Ok || !doc.containsKey("mode")) {
        return self->sendError(req, "400 Bad Request", "expected {\\\"mode\\\":\\\"auto|local|network\\\"}");
    }
    if (!self->_ctl->setSourceMode(doc["mode"] | "")) {
        return self->sendError(req, "400 Bad Request", "mode must be auto, local or network");
    }
    snprintf(self->_jsonBuf, sizeof(self->_jsonBuf), "{\"ok\":true,\"mode\":\"%s\",\"active\":\"%s\"}",
             self->_ctl->sourceModeName(), self->_ctl->activeSourceName());
    return self->sendJson(req, "200 OK", self->_jsonBuf);
}

// server 接続 (config.json wifi.enabled) の切り替え: {"enabled":bool}。保存後に再起動して反映。
// config.json は LittleFS 上にあり OTA では更新できないため、球体側で書き換える経路。
esp_err_t SoloWebServer::onServer(httpd_req_t* req) {
    auto* self = static_cast<SoloWebServer*>(req->user_ctx);
    char body[96];
    size_t len = 0;
    if (!self->readBody(req, body, sizeof(body), len)) {
        return self->sendError(req, "400 Bad Request", "invalid body");
    }
    StaticJsonDocument<128> doc;
    if (deserializeJson(doc, body, len) != DeserializationError::Ok || !doc.containsKey("enabled")) {
        return self->sendError(req, "400 Bad Request", "expected {\\\"enabled\\\":bool}");
    }
    const bool on = doc["enabled"] | false;
    if (!self->_ctl->setServerEnabled(on)) {
        return self->sendError(req, "500 Internal Server Error", "failed to save config.json");
    }
    const bool reboot = doc["reboot"] | true;
    if (reboot) {
        self->_ctl->stop();
        self->_ctl->scheduleReboot(800);
    }
    snprintf(self->_jsonBuf, sizeof(self->_jsonBuf), "{\"ok\":true,\"enabled\":%s,\"reboot_in_ms\":%d}",
             on ? "true" : "false", reboot ? 800 : 0);
    return self->sendJson(req, "200 OK", self->_jsonBuf);
}

// 省電力: {"ap":bool, "ap_idle_min":0..1440, "modem_sleep":bool} (指定したキーだけ反映)。
// "ap":false は応答を返してから AP を止める (この UI の接続も切れる。再開は本体ボタン)。
esp_err_t SoloWebServer::onPower(httpd_req_t* req) {
    auto* self = static_cast<SoloWebServer*>(req->user_ctx);
    char body[128];
    size_t len = 0;
    if (!self->readBody(req, body, sizeof(body), len)) {
        return self->sendError(req, "400 Bad Request", "invalid body");
    }
    StaticJsonDocument<192> doc;
    if (deserializeJson(doc, body, len) != DeserializationError::Ok) {
        return self->sendError(req, "400 Bad Request", "invalid json");
    }
    if (doc.containsKey("ap_idle_min")) {
        const int m = doc["ap_idle_min"] | 0;
        if (m < 0 || m > 1440) {
            return self->sendError(req, "400 Bad Request", "ap_idle_min must be 0..1440");
        }
        self->_ctl->setApIdleMinutes((uint16_t)m);
    }
    if (doc.containsKey("modem_sleep")) {
        self->_ctl->setModemSleep(doc["modem_sleep"] | false);
    }
    if (doc.containsKey("ap")) {
        self->_ctl->requestAp(doc["ap"] | true);
    }
    snprintf(self->_jsonBuf, sizeof(self->_jsonBuf), "{\"ok\":true}");
    return self->sendJson(req, "200 OK", self->_jsonBuf);
}

esp_err_t SoloWebServer::onWifi(httpd_req_t* req) {
    auto* self = static_cast<SoloWebServer*>(req->user_ctx);
    char body[192];
    size_t len = 0;
    if (!self->readBody(req, body, sizeof(body), len)) {
        return self->sendError(req, "400 Bad Request", "invalid body");
    }
    StaticJsonDocument<256> doc;
    if (deserializeJson(doc, body, len) != DeserializationError::Ok) {
        return self->sendError(req, "400 Bad Request", "expected json {ssid, password}");
    }
    const char* ssid = doc["ssid"] | "";
    const char* pass = doc["password"] | "";
    if (strlen(ssid) > 32 || strlen(pass) > 63) {
        return self->sendError(req, "400 Bad Request", "ssid/password too long");
    }
    // 空 SSID = 無効化。反映は次回起動から (稼働中に mode を変えると AP が落ちるため)
    if (!NetworkManager::saveStaCredentials(String(ssid), String(pass))) {
        return self->sendError(req, "500 Internal Server Error", "failed to save credentials");
    }
    snprintf(self->_jsonBuf, sizeof(self->_jsonBuf),
             "{\"ok\":true,\"ssid\":\"%s\",\"note\":\"reboot to apply\"}", ssid);
    return self->sendJson(req, "200 OK", self->_jsonBuf);
}

esp_err_t SoloWebServer::onLed(httpd_req_t* req) {
    auto* self = static_cast<SoloWebServer*>(req->user_ctx);
    char body[160];
    size_t len = 0;
    if (!self->readBody(req, body, sizeof(body), len)) {
        return self->sendError(req, "400 Bad Request", "invalid body");
    }
    StaticJsonDocument<192> doc;
    if (deserializeJson(doc, body, len) != DeserializationError::Ok) {
        return self->sendError(req, "400 Bad Request", "invalid json");
    }

    // 指定されたキーだけを反映する (mode / pattern / width / axis はそれぞれ独立)。
    // 実際の適用は DeviceController (MQTT の led コマンドと同じ経路)。
    DeviceController& ctl = *self->_ctl;
    if (doc.containsKey("pattern") || doc.containsKey("width")) {
        const char* pat = doc["pattern"] | ctl.testPatternName();
        const int w = doc["width"] | (int)ctl.testWidth();
        if (w < 1 || w > 60) {
            return self->sendError(req, "400 Bad Request", "width out of range (1-60)");
        }
        if (!ctl.setTestPattern(pat, w)) {
            return self->sendError(req, "400 Bad Request", "pattern must be strip or chase");
        }
    }
    if (doc.containsKey("mode")) {
        DeviceController::LedMode m;
        if (!DeviceController::parseLedMode(doc["mode"] | "", m)) {
            return self->sendError(req, "400 Bad Request", "mode must be sphere, test, off or pixels");
        }
        ctl.setLedMode(m);
    }
    if (doc.containsKey("axis")) {
        ctl.setAxisIndicator(doc["axis"] | false);
    }

    snprintf(self->_jsonBuf, sizeof(self->_jsonBuf),
             "{\"ok\":true,\"mode\":\"%s\",\"pattern\":\"%s\",\"width\":%u,\"axis\":%s}",
             ctl.ledModeName(), ctl.testPatternName(), (unsigned)ctl.testWidth(),
             ctl.axisIndicator() ? "true" : "false");
    return self->sendJson(req, "200 OK", self->_jsonBuf);
}

// IMU 診断 (GET): カウンタ・キャリブレーション・設定。?dump=1 で imu_dump の生サンプル
// (12B/サンプル hex、8 サンプル/行) を溜まっている分だけ返す。
esp_err_t SoloWebServer::onImuGet(httpd_req_t* req) {
    auto* self = static_cast<SoloWebServer*>(req->user_ctx);
    httpd_resp_set_type(req, "application/json");
    httpd_resp_set_hdr(req, "Cache-Control", "no-store");
    if (!self->_imu || !self->_imu->isInitialized()) {
        return httpd_resp_send(req, "{\"ok\":false,\"error\":\"imu not initialized\"}", HTTPD_RESP_USE_STRLEN);
    }
    IMUManager& imu = *self->_imu;
    uint8_t cs = 0, cg = 0, ca = 0, cm = 0;
    imu.getCalibration(cs, cg, ca, cm);
    float w = 0, x = 0, y = 0, z = 0;
    imu.getQuaternion(w, x, y, z);
    int len = snprintf(self->_jsonBuf, sizeof(self->_jsonBuf),
        "{\"ok\":true,\"now\":%lu,\"i2c_khz\":%lu,\"word_read\":%s,\"aux\":%s,\"smooth\":%u,\"mode\":%u,"
        "\"cal\":\"%u%u%u%u\",\"quat\":[%.4f,%.4f,%.4f,%.4f],\"seq\":%lu,"
        "\"reads\":%u,\"fails\":%u,\"discards\":%u,\"zero\":%u,\"partial\":%u,\"straddle\":%u,"
        "\"upd_us\":%u,\"upd_us_max\":%u,\"cycle_us\":%u,\"quat_us\":%u,\"timing_samples\":%u,\"task_running\":%s",
        (unsigned long)millis(), (unsigned long)(imu.i2cClock() / 1000), imu.wordRead() ? "true" : "false",
        imu.auxReads() ? "true" : "false", (unsigned)imu.smoothFrames(), (unsigned)imu.getOperationMode(),
        cs, cg, ca, cm, w, x, y, z, (unsigned long)imu.quatSeq(),
        (unsigned)imu.debugReadTotal(), (unsigned)imu.debugReadFails(), (unsigned)imu.debugDiscards(),
        (unsigned)imu.debugZeroReads(), (unsigned)imu.debugPartialReads(), (unsigned)imu.debugStraddles(),
        (unsigned)imu.debugUpdateUsAvg(), (unsigned)imu.debugUpdateUsMax(),
        (unsigned)imu.debugCycleUsAvg(), (unsigned)imu.debugQuatUsAvg(),
        (unsigned)imu.debugTimingSamples(), imu.debugTaskRunning() ? "true" : "false");
    httpd_resp_send_chunk(req, self->_jsonBuf, len);
    char q[16];
    if (httpd_req_get_url_query_str(req, q, sizeof(q)) == ESP_OK && strstr(q, "dump=1")) {
        httpd_resp_send_chunk(req, ",\"dump\":[", HTTPD_RESP_USE_STRLEN);
        static char hex[200];
        uint16_t idx0 = 0;
        for (int k = 0; k < 250 && imu.takeRawDumpLine(hex, sizeof(hex), idx0); k++) {
            len = snprintf(self->_jsonBuf, sizeof(self->_jsonBuf), "%s[%u,\"%s\"]", k ? "," : "", (unsigned)idx0, hex);
            httpd_resp_send_chunk(req, self->_jsonBuf, len);
        }
        httpd_resp_send_chunk(req, "]", 1);
    }
    httpd_resp_send_chunk(req, "}", 1);
    return httpd_resp_send_chunk(req, nullptr, 0);
}

// IMU 操作 (POST): {"smooth_frames":1..50} {"reset":true} {"i2c_khz":50..400}
//                  {"aux":bool} {"word_read":bool} {"dump":N (<=2000 サンプルを PSRAM に記録)}
esp_err_t SoloWebServer::onImuPost(httpd_req_t* req) {
    auto* self = static_cast<SoloWebServer*>(req->user_ctx);
    if (!self->_imu || !self->_imu->isInitialized()) {
        return self->sendError(req, "409 Conflict", "imu not initialized");
    }
    char body[160];
    size_t len = 0;
    if (!self->readBody(req, body, sizeof(body), len)) {
        return self->sendError(req, "400 Bad Request", "invalid body");
    }
    StaticJsonDocument<192> doc;
    if (deserializeJson(doc, body, len) != DeserializationError::Ok) {
        return self->sendError(req, "400 Bad Request", "invalid json");
    }
    IMUManager& imu = *self->_imu;
    DeviceController& ctl = *self->_ctl;
    if (doc.containsKey("smooth_frames") && !ctl.setImuSmooth(doc["smooth_frames"] | 1)) {
        return self->sendError(req, "400 Bad Request", "smooth_frames out of range");
    }
    if (doc.containsKey("i2c_khz") && !ctl.setImuI2cKhz(doc["i2c_khz"] | 100)) {
        return self->sendError(req, "400 Bad Request", "i2c_khz out of range (50-400)");
    }
    if (doc.containsKey("aux")) ctl.setImuAux(doc["aux"] | true);
    if (doc.containsKey("word_read")) ctl.setImuWordRead(doc["word_read"] | true);
    if (doc.containsKey("reset") && (doc["reset"] | false)) ctl.imuReset();
    if (doc.containsKey("reset_timing") && (doc["reset_timing"] | false)) ctl.imuResetTiming();
    if (doc.containsKey("dump") && !ctl.imuDump(doc["dump"] | 0)) {
        return self->sendError(req, "400 Bad Request", "dump must be 1-2000 (or PSRAM alloc failed)");
    }
    snprintf(self->_jsonBuf, sizeof(self->_jsonBuf),
             "{\"ok\":true,\"smooth\":%u,\"i2c_khz\":%lu,\"aux\":%s,\"word_read\":%s}",
             (unsigned)imu.smoothFrames(), (unsigned long)(imu.i2cClock() / 1000),
             imu.auxReads() ? "true" : "false", imu.wordRead() ? "true" : "false");
    return self->sendJson(req, "200 OK", self->_jsonBuf);
}

esp_err_t SoloWebServer::onBrightness(httpd_req_t* req) {
    auto* self = static_cast<SoloWebServer*>(req->user_ctx);
    char body[128];
    size_t len = 0;
    if (!self->readBody(req, body, sizeof(body), len)) {
        return self->sendError(req, "400 Bad Request", "invalid body");
    }
    StaticJsonDocument<128> doc;
    if (deserializeJson(doc, body, len) != DeserializationError::Ok || !doc.containsKey("value")) {
        return self->sendError(req, "400 Bad Request", "expected {\\\"value\\\":0-100}");
    }
    int v = doc["value"] | -1;
    if (v < 0 || v > 100) {
        return self->sendError(req, "400 Bad Request", "value out of range (0-100)");
    }
    self->_ctl->setBrightnessPct((uint8_t)v);
    snprintf(self->_jsonBuf, sizeof(self->_jsonBuf), "{\"ok\":true,\"brightness\":%d}", v);
    return self->sendJson(req, "200 OK", self->_jsonBuf);
}

esp_err_t SoloWebServer::onUpload(httpd_req_t* req) {
    auto* self = static_cast<SoloWebServer*>(req->user_ctx);
    return self->doUpload(req);
}

esp_err_t SoloWebServer::doUpload(httpd_req_t* req) {
    const size_t len = req->content_len;
    if (len == 0) {
        return sendError(req, "400 Bad Request", "empty body");
    }

    size_t fsFree = 0, existing = 0;
    refreshFsUsage();   // ここは実値が要る (書き込む直前)
    const size_t maxUpload = maxUploadBytes(fsFree, existing);
    if (len > maxUpload) {
        snprintf(_jsonBuf, sizeof(_jsonBuf),
                 "{\"ok\":false,\"error\":\"insufficient storage\",\"content_length\":%u,\"max_upload\":%u,\"free\":%u}",
                 (unsigned)len, (unsigned)maxUpload, (unsigned)fsFree);
        return sendJson(req, "507 Insufficient Storage", _jsonBuf);
    }
    // 一時ファイル + 既存動画 の二重保持ができない場合だけ、先に既存動画を消す
    const bool deleteFirst = (len + kFsMargin > fsFree);

    if (!_player->beginUpload()) {
        return sendError(req, "409 Conflict", "upload already in progress");
    }

    const String videoPath = _player->videoPath();
    if (deleteFirst && LittleFS.exists(videoPath.c_str())) {
        Serial.println("[SoloWeb] Removing current video to make room for upload");
        LittleFS.remove(videoPath.c_str());
    }
    if (LittleFS.exists(kTmpPath)) {
        LittleFS.remove(kTmpPath);
    }

    const char* err = nullptr;
    size_t received = 0;
    {
        fs::File f = LittleFS.open(kTmpPath, "w");
        if (!f) {
            err = "failed to create temp file";
        } else {
            size_t remaining = len;
            int timeouts = 0;
            while (remaining > 0) {
                const size_t want = remaining < kRxBufSize ? remaining : kRxBufSize;
                const int r = httpd_req_recv(req, (char*)_rxBuf, want);
                if (r == HTTPD_SOCK_ERR_TIMEOUT) {
                    if (++timeouts > kRecvTimeoutRetries) {
                        err = "receive timeout";
                        break;
                    }
                    continue;
                }
                if (r <= 0) {
                    err = "connection lost during upload";
                    break;
                }
                timeouts = 0;
                if (f.write(_rxBuf, (size_t)r) != (size_t)r) {
                    err = "write failed (storage full?)";
                    break;
                }
                remaining -= (size_t)r;
                received += (size_t)r;
            }
            f.close();
        }
    }

    MjpegInfo info;
    if (!err) {
        const char* verr = nullptr;
        if (!_player->validateFile(kTmpPath, info, &verr)) {
            err = verr ? verr : "invalid video";
        }
    }
    if (!err) {
        if (LittleFS.exists(videoPath.c_str())) {
            LittleFS.remove(videoPath.c_str());
        }
        if (!LittleFS.rename(kTmpPath, videoPath.c_str())) {
            err = "failed to install video";
        }
    }

    if (err) {
        LittleFS.remove(kTmpPath);
        _uploadFailures++;
        _player->endUpload();  // 旧動画が残っていればそれを再生、無ければ no_video
        refreshFsUsage();
        Serial.printf("[SoloWeb] Upload failed: %s (received %u/%u bytes)\n", err, (unsigned)received, (unsigned)len);
        snprintf(_jsonBuf, sizeof(_jsonBuf),
                 "{\"ok\":false,\"error\":\"%s\",\"received\":%u,\"expected\":%u,\"replaced_before_upload\":%s,"
                 "\"got_width\":%u,\"got_height\":%u,\"state\":\"%s\"}",
                 err, (unsigned)received, (unsigned)len, deleteFirst ? "true" : "false",
                 (unsigned)info.width, (unsigned)info.height, _player->stateName());
        sendJson(req, "400 Bad Request", _jsonBuf);
        // 受信途中で切れた場合は本文が残っているので接続を閉じさせる
        return (received == len) ? ESP_OK : ESP_FAIL;
    }

    _uploads++;
    _player->endUpload();  // 新しい動画を先頭から再生 (PSRAM への読み込み込みで数秒かかる)
    refreshFsUsage();
    Serial.printf("[SoloWeb] Upload ok: %u frames, %u bytes, max frame %u\n",
                  (unsigned)info.frames, (unsigned)info.fileBytes, (unsigned)info.maxFrameBytes);
    snprintf(_jsonBuf, sizeof(_jsonBuf),
             "{\"ok\":true,\"frames\":%u,\"bytes\":%u,\"max_frame_bytes\":%u,\"duration_s\":%.1f,"
             "\"replaced_before_upload\":%s,\"state\":\"%s\"}",
             (unsigned)info.frames, (unsigned)info.fileBytes, (unsigned)info.maxFrameBytes,
             (float)info.frames / (float)kSoloFps, deleteFirst ? "true" : "false", _player->stateName());
    return sendJson(req, "200 OK", _jsonBuf);
}

esp_err_t SoloWebServer::onDelete(httpd_req_t* req) {
    auto* self = static_cast<SoloWebServer*>(req->user_ctx);
    if (!self->_player->beginUpload()) {
        return self->sendError(req, "409 Conflict", "upload in progress");
    }
    const String path = self->_player->videoPath();
    bool removed = false;
    if (LittleFS.exists(path.c_str())) {
        removed = LittleFS.remove(path.c_str());
    }
    self->_player->endUpload();
    self->refreshFsUsage();
    snprintf(self->_jsonBuf, sizeof(self->_jsonBuf), "{\"ok\":true,\"removed\":%s,\"state\":\"%s\"}",
             removed ? "true" : "false", self->_player->stateName());
    return self->sendJson(req, "200 OK", self->_jsonBuf);
}

esp_err_t SoloWebServer::onReboot(httpd_req_t* req) {
    auto* self = static_cast<SoloWebServer*>(req->user_ctx);
    self->_ctl->stop();
    self->_ctl->scheduleReboot(500);
    return self->sendJson(req, "200 OK", "{\"ok\":true,\"reboot_in_ms\":500}");
}

esp_err_t SoloWebServer::onNotFound(httpd_req_t* req, httpd_err_code_t) {
    if (strncmp(req->uri, "/api/", 5) == 0) {
        httpd_resp_set_status(req, "404 Not Found");
        httpd_resp_set_type(req, "application/json");
        return httpd_resp_send(req, "{\"ok\":false,\"error\":\"not found\"}", HTTPD_RESP_USE_STRLEN);
    }
    // キャプティブポータル検出プローブ (iOS/macOS: /hotspot-detect.html,
    // Android: /generate_204, Windows: /connecttest.txt など)。
    //   captive_portal = false (既定): 期待どおりの応答を返し「ログイン」画面を開かせない。
    //     iOS の CNA はファイル選択ダイアログが出ず動画をアップロードできないため、
    //     最初から Safari で開いてもらう (利用者が URL を自分で開く)。
    //   captive_portal = true: 応答せずリダイレクトし、接続と同時に UI を自動表示する。
    auto* self = static_cast<SoloWebServer*>(req->user_ctx);
    const bool captive = (self && self->_config) ? self->_config->getSoloCaptivePortal() : false;
    if (!captive) {
        const char* uri = req->uri;
        httpd_resp_set_hdr(req, "Cache-Control", "no-store");
        if (strcmp(uri, "/generate_204") == 0 || strcmp(uri, "/gen_204") == 0) {
            httpd_resp_set_status(req, "204 No Content");
            return httpd_resp_send(req, nullptr, 0);
        }
        if (strcmp(uri, "/hotspot-detect.html") == 0 ||
            strcmp(uri, "/library/test/success.html") == 0) {
            httpd_resp_set_type(req, "text/html");
            return httpd_resp_send(req,
                "<HTML><HEAD><TITLE>Success</TITLE></HEAD><BODY>Success</BODY></HTML>",
                HTTPD_RESP_USE_STRLEN);
        }
        if (strcmp(uri, "/success.txt") == 0) {
            httpd_resp_set_type(req, "text/plain");
            return httpd_resp_send(req, "success", HTTPD_RESP_USE_STRLEN);
        }
        if (strcmp(uri, "/connecttest.txt") == 0) {
            httpd_resp_set_type(req, "text/plain");
            return httpd_resp_send(req, "Microsoft Connect Test", HTTPD_RESP_USE_STRLEN);
        }
        if (strcmp(uri, "/ncsi.txt") == 0) {
            httpd_resp_set_type(req, "text/plain");
            return httpd_resp_send(req, "Microsoft NCSI", HTTPD_RESP_USE_STRLEN);
        }
    }
    // プローブ以外の未知パス (ユーザーが何か入力した等) は UI へ誘導する
    char location[64];
    snprintf(location, sizeof(location), "http://%s/?cna=1", WiFi.softAPIP().toString().c_str());
    httpd_resp_set_status(req, "302 Found");
    httpd_resp_set_hdr(req, "Location", location);
    httpd_resp_set_hdr(req, "Cache-Control", "no-store");
    httpd_resp_set_type(req, "text/plain");
    return httpd_resp_send(req, "redirect", HTTPD_RESP_USE_STRLEN);
}

}  // namespace sastle
