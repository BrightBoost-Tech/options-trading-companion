import React from 'react';
import { formatOptionDisplay } from '@/lib/formatters';
import { Wallet, RefreshCw, Copy, Check } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { useToast } from '@/components/ui/use-toast';

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
  const { toast } = useToast();
  const [copiedSymbol, setCopiedSymbol] = React.useState<string | null>(null);

  const handleCopy = (text: string) => {
    navigator.clipboard.writeText(text);
    setCopiedSymbol(text);
    toast({
      description: "Symbol copied to clipboard",
    });
    setTimeout(() => setCopiedSymbol(null), 2000);
  };

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
        if (s === 'critical') return 'bg-red-100 text-red-800 dark:bg-red-900/30 dark:text-red-400';
        if (s === 'warning') return 'bg-yellow-100 text-yellow-800 dark:bg-yellow-900/30 dark:text-yellow-400';
        if (s === 'success') return 'bg-green-100 text-green-800 dark:bg-green-900/30 dark:text-green-400';
        return '';
      };

      // Use backend provided display_symbol if available, otherwise format locally
      const displaySymbol = position.display_symbol ?? (type === 'option' ? formatOptionDisplay(position.symbol) : position.symbol);

      return (
        <tr key={`${position.symbol}-${idx}`} className="hover:bg-muted/50 transition-colors group">
            <th scope="row" className={`px-6 py-4 font-medium text-left ${type === 'option' ? 'text-purple-600 dark:text-purple-400' : 'text-foreground'}`}>
                <div className="flex flex-col items-start gap-1">
                    <button
                        onClick={() => handleCopy(displaySymbol)}
                        className="flex items-center gap-2 hover:opacity-80 transition-opacity text-left"
                        title="Click to copy symbol"
                        aria-label={`Copy symbol ${displaySymbol}`}
                    >
                        <span>{displaySymbol}</span>
                        {copiedSymbol === displaySymbol ? (
                            <Check className="w-3 h-3 text-green-500 animate-in fade-in zoom-in" aria-hidden="true" />
                        ) : (
                            <Copy className="w-3 h-3 text-muted-foreground opacity-0 group-hover:opacity-100 transition-opacity" aria-hidden="true" />
                        )}
                    </button>
                    {position.sector && (
                        <span className="text-[10px] text-muted-foreground uppercase">{position.sector}</span>
                    )}
                </div>
            </th>
            <td className="px-6 py-4">{position.quantity}</td>
            <td className="px-6 py-4">${position.cost_basis?.toFixed(2)}</td>
            <td className="px-6 py-4">
                <div>${position.current_price?.toFixed(2)}</div>
                <div className="text-xs text-muted-foreground">Val: ${value.toFixed(0)}</div>
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
      <table className="w-full" aria-label="Portfolio Holdings">
        <thead className="bg-muted border-b border-border">
          <tr>
            <th scope="col" className="px-6 py-3 text-left text-xs font-medium text-muted-foreground uppercase">Symbol</th>
            <th scope="col" className="px-6 py-3 text-left text-xs font-medium text-muted-foreground uppercase">Qty</th>
            <th scope="col" className="px-6 py-3 text-left text-xs font-medium text-muted-foreground uppercase">Avg Cost</th>
            <th scope="col" className="px-6 py-3 text-left text-xs font-medium text-muted-foreground uppercase">Price</th>
            <th scope="col" className="px-6 py-3 text-left text-xs font-medium text-muted-foreground uppercase">P&L</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-border">
            {optionHoldings.length > 0 && (
                 <>
                    <tr className="bg-purple-50 dark:bg-purple-900/20 border-b border-purple-100 dark:border-purple-900/30">
                        <th scope="rowgroup" colSpan={5} className="px-6 py-2 text-left text-xs font-bold text-purple-800 dark:text-purple-300 uppercase">🎯 Option Plays</th>
                    </tr>
                    {optionHoldings.map((h, i) => renderPositionRow(h, i))}
                 </>
            )}

            {equityHoldings.length > 0 && (
                 <>
                    <tr className="bg-blue-50 dark:bg-blue-900/20 border-b border-blue-100 dark:border-blue-900/30">
                        <th scope="rowgroup" colSpan={5} className="px-6 py-2 text-left text-xs font-bold text-blue-800 dark:text-blue-300 uppercase">📈 Long Term Holds</th>
                    </tr>
                    {equityHoldings.map((h, i) => renderPositionRow(h, i))}
                 </>
            )}

            {cashHoldings.length > 0 && (
                <>
                     <tr className="bg-green-50 dark:bg-green-900/20 border-b border-green-100 dark:border-green-900/30">
                        <th scope="rowgroup" colSpan={5} className="px-6 py-2 text-left text-xs font-bold text-green-800 dark:text-green-300 uppercase">💵 Cash & Equiv</th>
                    </tr>
                    {cashHoldings.map((position, idx) => (
                        <tr key={`cash-${idx}`} className="bg-green-50/50 dark:bg-green-900/10 border-t border-green-100 dark:border-green-900/30">
                            <th scope="row" className="px-6 py-4 font-bold text-left text-green-800 dark:text-green-300">
                                {position.symbol === 'CUR:USD' ? 'USD CASH' : position.symbol}
                            </th>
                            <td className="px-6 py-4 text-green-800 dark:text-green-300">---</td>
                            <td className="px-6 py-4 text-green-800 dark:text-green-300">---</td>
                            <td className="px-6 py-4 font-bold text-green-800 dark:text-green-300">${position.quantity?.toFixed(2)}</td>
                            <td className="px-6 py-4"><span className="text-xs bg-green-200 dark:bg-green-900 text-green-800 dark:text-green-300 px-2 py-1 rounded">Sweep</span></td>
                        </tr>
                    ))}
                </>
            )}

            {holdings.length === 0 && (
                 <tr>
                    <td colSpan={5} className="py-12 text-center">
                        <div className="flex flex-col items-center justify-center space-y-3">
                            <div className="bg-muted p-4 rounded-full">
                                <Wallet className="w-8 h-8 text-muted-foreground" aria-hidden="true" />
                            </div>
                            <div className="space-y-1">
                                <h3 className="text-lg font-medium">No Holdings Found</h3>
                                <p className="text-sm text-muted-foreground max-w-[300px] mx-auto">
                                    Sync your brokerage account via Plaid or import a CSV to get started.
                                </p>
                            </div>
                            <div className="pt-2">
                                <Button
                                    onClick={onSync}
                                    variant="outline"
                                    aria-label="Sync holdings now"
                                >
                                    <RefreshCw className="mr-2 h-4 w-4" aria-hidden="true" />
                                    Sync Now
                                </Button>
                            </div>
                        </div>
                    </td>
                  </tr>
            )}
        </tbody>
      </table>
    </div>
  );
}
