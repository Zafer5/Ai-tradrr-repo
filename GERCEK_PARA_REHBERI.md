# Gerçek para rehberi (önce oku)

> **Dürüst durum:** Bu bot henüz geçmiş verilerle (backtest) sınanmadı, gerçek Binance hesabıyla
> da denenmedi. Kâr edeceğine dair **hiçbir kanıt yok**. Gerçek para modu, bu yazılımı
> *denemek* içindir; kaybetmeyi göze alabileceğin bir tutarla başla. Kaybettiğinde zarar sana aittir.

## Önerilen sıra (atlama)
1. **Sanal mod** (şu anki): Birkaç gün çalıştır. "Kâr-Zarar" sekmesinde net kâr, azami düşüş ve
   kâr faktörüne bak. Sadece kazanç oranına bakma.
2. **Testnet:** Sahte parayla gerçek emir akışını dene (emir gidiyor mu, satış çalışıyor mu).
3. **Gerçek mod:** Çok küçük tutarla, bilgisayar başında izleyerek.

## Testnet (sahte para)
1. https://testnet.binance.vision adresine GitHub hesabınla gir, "Generate HMAC_SHA256 Key" ile anahtar al.
2. `.env` dosyasında `TRADING_MODE=testnet` yap, `baslat.bat`'ı yeniden çalıştır.
3. Panel, Bağlantılar sekmesi: anahtarı gir, "Güvenlik kontrolünü çalıştır", sonra botu başlat.
Testnet fiyatları ve hacimleri gerçeğe benzemez; amaç yalnızca emir akışını denemektir.

## Gerçek mod
### 1) Binance'te API anahtarı
- Hesap, API Yönetimi, yeni anahtar. **Sadece "Spot alım-satım" izni** açık olsun.
- **"Para çekme" izni KAPALI** olmalı. Açıksa bot çalışmayı reddeder.
- Vadeli işlem / kaldıraç / marjin izinleri KAPALI.
- **IP kısıtlaması** koy (bu bilgisayarın internet IP adresi; ev internetinde zamanla değişebilir).
- Secret anahtarı kimseye, bana da, sohbete yazma. Sadece panelde "Bağlantılar" sekmesine gir.

### 2) Hesaba koyacağın para
Hesaba **en fazla bot bütçesi kadar** USDT koy.

### 3) `.env` dosyası
```
TRADING_MODE=live
LIVE_CONFIRM=GERCEK-PARA-RISKINI-KABUL-EDIYORUM
LIVE_BUDGET_USDT=30
LIVE_MAX_ORDER_USDT=10
```
Bunlar yazılmadan bot gerçek modda açılmaz. Bütçe en fazla 1000 USDT olabilir (güvenlik sınırı).
`baslat.bat`'ı yeniden çalıştır. Üstte kırmızı **GERÇEK PARA** uyarısı çıkar.

### 4) Başlatma
Bağlantılar sekmesinde anahtarı gir, "Güvenlik kontrolünü çalıştır" (hepsi ✅ olmalı), sonra
Ana Sayfa'da başlat. Onay için **ONAYLIYORUM** yazman istenir.

## Küçük bütçe uyarısı
Binance, çoğu coinde en az ~5-10 USDT'lik emir ister. Varsayılan risk kuralları
("tek coine en fazla %5") 30 USDT bütçede 1,5 USDT eder; bu yüzden bot **hiç alım yapmayabilir**
ve Canlı sekmesinde "işlem tutarı çok küçük" yazar. Çözüm: bütçeyi artırmak (örn. 100 USDT) ya da
Risk sekmesinde "Tek coine en fazla %"yi yükseltmek. İkincisi, her işlemde bütçenin büyük kısmını riske atmak demektir.

## Koruma katmanları
- Gerçek mod `.env` onay satırı olmadan açılmaz; her başlatmada ONAYLIYORUM yazılır.
- Para çekme izni açık anahtar reddedilir.
- Bot bütçesi ve tek alım sınırı `.env`'de; panelden aşılamaz.
- Günlük zarar limiti, azami pozisyon sayısı, acil durdurma, mükerrer emir engeli.
- Emir sonucu belirsizse bot kendini durdurur ve o coine dokunmaz.
- Yeni listelenen coinlere bot kendiliğinden girmez (Radar yalnızca izleme içindir).

## Bilmen gereken riskler
- **Bilgisayar kapanırsa ya da internet giderse stop-loss çalışmaz.** Zarar kesme emri borsada değil,
  botun içinde bekler. Pozisyon açıkken bilgisayarı kapatma, uyutma.
- Ani düşüşlerde stop fiyatından çok aşağıda satılabilir (kayma).
- Piyasa emri kullanılır; likidite düşükse beklenenden kötü fiyat gelir.
- Yazılım hatası olabilir. Bu bot sınırlı denendi; Binance'e gerçek bağlantı henüz sınanmadı.
- Yeni ve ani yükselen coinler en çok para kaybettiren coinlerdir. Radar bir tahmin değildir.
- Vergi ve yasal yükümlülükler sana aittir.

## Acil durum
Panelde **ACİL DURDUR** (yeni alımları keser, istersen pozisyonları kapatır). Panele ulaşamazsan
Binance'e girip anahtarı sil ya da devre dışı bırak: bot anında emir gönderemez hale gelir.
