export function renderPrice(value: number, symbol: string): string {
  const cents = Math.round(value * 100) / 100;
  const prefix = cents < 0 ? "-" : "";
  const magnitude = Math.abs(cents).toFixed(2);
  return `${prefix}${symbol}${magnitude}`;
}
