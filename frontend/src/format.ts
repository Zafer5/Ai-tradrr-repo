const TZ = "Europe/Istanbul";

export function usd(n: number | null | undefined, d = 2): string {
  if (n === null || n === undefined || Number.isNaN(n)) return "-";
  return n.toLocaleString("tr-TR", { minimumFractionDigits: d, maximumFractionDigits: d });
}

export function signed(n: number | null | undefined, d = 2): string {
  if (n === null || n === undefined || Number.isNaN(n)) return "-";
  return (n > 0 ? "+" : "") + usd(n, d);
}

export function pct(n: number | null | undefined, d = 2, sign = false): string {
  if (n === null || n === undefined || Number.isNaN(n)) return "-";
  return (sign && n > 0 ? "+" : "") + usd(n, d) + "%";
}

/** Fiyatın büyüklüğüne göre uygun ondalık basamak */
export function price(n: number | null | undefined): string {
  if (n === null || n === undefined || Number.isNaN(n)) return "-";
  const a = Math.abs(n);
  const d = a >= 1000 ? 2 : a >= 10 ? 3 : a >= 1 ? 4 : a >= 0.1 ? 5 : a >= 0.01 ? 6 : 8;
  return n.toLocaleString("tr-TR", { minimumFractionDigits: 0, maximumFractionDigits: d });
}

export function compact(n: number | null | undefined): string {
  if (n === null || n === undefined) return "-";
  return n.toLocaleString("tr-TR", { notation: "compact", maximumFractionDigits: 1 });
}

export function time(iso: string | null | undefined): string {
  if (!iso) return "-";
  return new Date(iso).toLocaleString("tr-TR", { timeZone: TZ, day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit" });
}

export function timeFull(iso: string | null | undefined): string {
  if (!iso) return "-";
  return new Date(iso).toLocaleString("tr-TR", { timeZone: TZ, day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit", second: "2-digit" });
}

export function ago(sec: number | null | undefined): string {
  if (sec === null || sec === undefined) return "hiç";
  if (sec < 90) return `${Math.round(sec)} sn önce`;
  if (sec < 5400) return `${Math.round(sec / 60)} dk önce`;
  return `${(sec / 3600).toFixed(1)} sa önce`;
}

export const tone = (n: number | null | undefined): string => (n === null || n === undefined || n === 0 ? "" : n > 0 ? "pos" : "neg");

export const coin = (symbol: string): string => symbol.replace(/USDT$/, "");
