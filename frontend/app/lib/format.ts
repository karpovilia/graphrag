// Small formatters reused across pages.

export function formatRelativeTime(iso: string | null | undefined): string {
  if (!iso) return "—";
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return "—";
  const diffMs = Date.now() - date.getTime();
  const diffSec = Math.round(diffMs / 1000);
  if (diffSec < 5) return "только что";
  if (diffSec < 60) return `${diffSec} с назад`;
  const diffMin = Math.round(diffSec / 60);
  if (diffMin < 60) return `${diffMin} мин назад`;
  const diffHr = Math.round(diffMin / 60);
  if (diffHr < 24) return `${diffHr} ч назад`;
  const diffDay = Math.round(diffHr / 24);
  if (diffDay < 30) return `${diffDay} дн назад`;
  return date.toLocaleDateString("ru-RU");
}

export function formatNumber(n: number | null | undefined): string {
  if (n == null) return "—";
  return new Intl.NumberFormat("ru-RU").format(n);
}

export function formatPercent(p: number | null | undefined, fractionDigits = 0): string {
  if (p == null) return "—";
  return `${(p * 100).toFixed(fractionDigits)}%`;
}
