
export interface ParsedOptionSymbol {
  underlying: string;
  expiry?: string;    // "YYYY-MM-DD"
  type?: 'C' | 'P';
  strike?: number;
}

export function parseOptionSymbol(symbol: string): ParsedOptionSymbol | null {
  if (!symbol) return null;

  // Strip Polygon-style prefix if present
  const clean = symbol.replace(/^O:/, '');

  // OCC-style pattern: UNDERLYYYYMMDDC/PStrike*1000*
  // Example: KURA260417C00010000
  const match = clean.match(/^([A-Z\.\-]+)(\d{2})(\d{2})(\d{2})([CP])(\d{8})$/);
  if (!match) return null;

  const [, underlying, yy, mm, dd, cp, strikeRaw] = match;
  const year = 2000 + Number(yy);
  const month = Number(mm);
  const day = Number(dd);
  const strike = Number(strikeRaw) / 1000;

  return {
    underlying,
    expiry: `${year}-${String(month).padStart(2, '0')}-${String(day).padStart(2, '0')}`,
    type: cp as 'C' | 'P',
    strike,
  };
}

export function formatOptionDisplay(symbol: string): string {
  const parsed = parseOptionSymbol(symbol);
  if (!parsed || !parsed.expiry || !parsed.type || parsed.strike === undefined) {
    return symbol;
  }

  const { underlying, expiry, type, strike } = parsed;
  // expiry is YYYY-MM-DD
  const [year, month, day] = expiry.split('-');
  const shortDate = `${month}/${day}/${year.slice(2)}`;

  return `${underlying} ${shortDate} ${strike}${type}`;
}

export interface OptionLeg {
  symbol: string;
  quantity: number;
  current_price: number;
  cost_basis?: number;
  parsed: ParsedOptionSymbol;
}

export interface OptionSpread {
  underlying: string;
  expiry: string;
  type: 'C' | 'P';
  legs: OptionLeg[];
}

export function groupOptionSpreads(holdings: any[]): OptionSpread[] {
  const spreadsByKey: Record<string, OptionSpread> = {};

  for (const h of holdings || []) {
    const parsed = parseOptionSymbol(h.symbol);
    if (!parsed || !parsed.expiry || !parsed.type) continue;

    const key = `${parsed.underlying}-${parsed.expiry}-${parsed.type}`;
    if (!spreadsByKey[key]) {
      spreadsByKey[key] = {
        underlying: parsed.underlying,
        expiry: parsed.expiry,
        type: parsed.type,
        legs: [],
      };
    }

    spreadsByKey[key].legs.push({
      symbol: h.symbol,
      quantity: Number(h.quantity || h.current_quantity || 0),
      current_price: Number(h.current_price || h.price || 0),
      cost_basis: h.cost_basis,
      parsed,
    });
  }

  return Object.values(spreadsByKey);
}
