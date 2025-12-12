import React from 'react';
import { formatOptionDisplay } from '@/lib/formatters';

interface PortfolioHoldingsTableProps {
  holdings: any[];
  onSync: () => void;
  onGenerateSuggestions: () => void;
}

const isLikelyOptionSymbol = (symbol: string | undefined): boolean => {
  if (!symbol) return false;
  // Mirror the OCC regex used in asset_classifier.is_occ_option_symbol:
  // r"^([A-Z\.-]+)(\d{6})([CP])(\d{8})$"
  const clean = symbol.replace("O:", "");
  return /^[A-Z\.-]+(\d{6})([CP])(\d{8})$/.test(clean);
};

export default function PortfolioHoldingsTable({ holdings, onSync, onGenerateSuggestions }: PortfolioHoldingsTableProps) {
  // --- HELPERS ---
  const renderPositionRow = (position: any, idx: number) => {
      const type = position.asset_type === 'OPTION' ? 'option' : 'stock';
      const cost = position.cost_basis * position.quantity;
      const value = position.current_price * position.quantity * (type === 'option' ? 100 : 1);
      const pnl = value - cost;

      const pnlPercent = position.pnl_percent !== undefined
        ? position.pnl_percent
        : (position.cost_basis > 0 ? (pnl / cost) * 100 : 0);

      const getSeverityClass = (s?: string) => {
        if (s === 'critical') return 'bg-red-100 text-red-800';
        if (s === 'warning') return 'bg-yellow-100 text-yellow-800';
        if (s === 'success') return 'bg-green-100 text-green-800';
        return '';
      };

      // Use backend provided display_symbol if available, otherwise format locally
      const displaySymbol = position.display_symbol ?? (type === 'option' ? formatOptionDisplay(position.symbol) : position.symbol);

      return (
        <tr key={`${position.symbol}-${idx}`} className="hover:bg-gray-50">
            <td className={`px-6 py-4 font-medium ${type === 'option' ? 'text-purple-600' : 'text-gray-900'}`}>
                <div className="flex flex-col">
                    <span>{displaySymbol}</span>
                    {position.sector && (
                        <span className="text-[10px] text-gray-400 uppercase">{position.sector}</span>
                    )}
                </div>
            </td>
            <td className="px-6 py-4">{position.quantity}</td>
            <td className="px-6 py-4">${position.cost_basis?.toFixed(2)}</td>
            <td className="px-6 py-4">
                <div>${position.current_price?.toFixed(2)}</div>
                <div className="text-xs text-gray-400">Val: ${value.toFixed(0)}</div>
            </td>
            <td className="px-6 py-4 whitespace-nowrap">
                <div className={`font-bold ${pnl >= 0 ? 'text-green-600' : 'text-red-600'}`}>
                {pnl >= 0 ? '+' : ''}{pnl.toFixed(2)} ({pnlPercent.toFixed(1)}%)
                </div>

                {position.pnl_severity && (
                   <span className={`inline-flex ml-2 items-center px-2 py-0.5 rounded text-xs font-medium ${getSeverityClass(position.pnl_severity)}`}>
                      {position.pnl_severity.toUpperCase()}
                   </span>
                )}
            </td>
        </tr>
      );
  };

  // Grouping Logic (Phase 8.1)
  // Treat '{}' as OPTION if asset_type says so OR symbol pattern looks like OCC.
  const optionHoldings = holdings.filter(h =>
    h.asset_type === 'OPTION' || (!h.asset_type && isLikelyOptionSymbol(h.symbol))
  );

  // Long Term / Equity holds:
  // - asset_type === 'EQUITY'
  // - OR legacy records with missing asset_type and NOT option-like and NOT cash
  const equityHoldings = holdings.filter(h =>
    (h.asset_type === 'EQUITY' || (!h.asset_type && !isLikelyOptionSymbol(h.symbol) && h.symbol !== 'CUR:USD')) &&
    // Optional: restrict to "true long-term" if we have is_locked/strategy_tag in holdings
    (h.is_locked || h.strategy_tag === 'LONG_TERM_HOLD' || h.symbol === 'VTSI')
  );

  const cashHoldings = holdings.filter(h => h.asset_type === 'CASH' || h.symbol === 'CUR:USD');

  return (
    <div className="overflow-x-auto">
      <table className="w-full">
        <thead className="bg-gray-50 border-b">
          <tr>
            <th scope="col" className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase">Symbol</th>
            <th scope="col" className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase">Qty</th>
            <th scope="col" className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase">Avg Cost</th>
            <th scope="col" className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase">Price</th>
            <th scope="col" className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase">P&L</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-gray-200">
            {optionHoldings.length > 0 && (
                 <>
                    <tr className="bg-purple-50">
                        <td colSpan={5} className="px-6 py-2 text-xs font-bold text-purple-800 uppercase">🎯 Option Plays</td>
                    </tr>
                    {optionHoldings.map((h, i) => renderPositionRow(h, i))}
                 </>
            )}

            {equityHoldings.length > 0 && (
                 <>
                    <tr className="bg-blue-50">
                        <td colSpan={5} className="px-6 py-2 text-xs font-bold text-blue-800 uppercase">📈 Long Term Holds</td>
                    </tr>
                    {equityHoldings.map((h, i) => renderPositionRow(h, i))}
                 </>
            )}

            {cashHoldings.length > 0 && (
                <>
                     <tr className="bg-green-50">
                        <td colSpan={5} className="px-6 py-2 text-xs font-bold text-green-800 uppercase">💵 Cash & Equiv</td>
                    </tr>
                    {cashHoldings.map((position, idx) => (
                        <tr key={`cash-${idx}`} className="bg-green-50 border-t-2 border-green-100">
                            <td className="px-6 py-4 font-bold text-green-800">
                                {position.symbol === 'CUR:USD' ? 'USD CASH' : position.symbol}
                            </td>
                            <td className="px-6 py-4 text-green-800">---</td>
                            <td className="px-6 py-4 text-green-800">---</td>
                            <td className="px-6 py-4 font-bold text-green-800">${position.quantity?.toFixed(2)}</td>
                            <td className="px-6 py-4"><span className="text-xs bg-green-200 text-green-800 px-2 py-1 rounded">Sweep</span></td>
                        </tr>
                    ))}
                </>
            )}

            {holdings.length === 0 && (
                 <tr>
                    <td colSpan={5} className="px-6 py-8 text-center text-gray-500">
                      No positions found. Sync via Plaid or Import CSV in Settings.
                    </td>
                  </tr>
            )}
        </tbody>
      </table>
    </div>
  );
}
