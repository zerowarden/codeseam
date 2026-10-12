export function formatCurrency(amount: number, currency: string): string {
  const rounded = Math.round(amount * 100) / 100;
  const sign = rounded < 0 ? "-" : "";
  const absolute = Math.abs(rounded).toFixed(2);
  return `${sign}${currency}${absolute}`;
}
