import React, { useState } from 'react';
import { Card, CardContent } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { QuantumTooltip } from '@/components/ui/QuantumTooltip';
import { API_URL, TEST_USER_ID } from '@/lib/constants';
import { Copy, CheckCircle2, Loader2 } from 'lucide-react';
import { formatOptionDisplay } from '@/lib/formatters';
import { supabase } from '@/lib/supabase';

interface TradeSuggestionMetrics {
  expected_value?: number;
  probability_of_profit?: number; // 0–100
}

interface TradeSuggestion {
  id?: string;
  symbol?: string;
  display_symbol?: string;
  ticker?: string;
  strategy?: string;
  type?: string;
  score?: number;
  badges?: string[];
  rationale?: string;
  metrics?: TradeSuggestionMetrics;
  price?: number;
  strike_price?: number;
  entry_price?: number;
  underlying_price?: number;
  width?: number;
  // New fields
  window?: string;
  order_json?: Record<string, any>;
  sizing_metadata?: Record<string, any>;
  ev?: number;

  // Compounding Mode
  sizing?: {
      recommended_contracts: number;
      ev_percent: number;
      ev_amount: number;
      rationale: string;
      kelly_fraction?: number;
  };
  compound_score?: number;
}

interface TradeSuggestionCardProps {
  suggestion: TradeSuggestion;
  onLogged?: (id: string) => void;
}

// Helper for safe numeric formatting
const safeFixed = (value: number | null | undefined, digits = 2) =>
  typeof value === "number" ? value.toFixed(digits) : "--";

export default function TradeSuggestionCard({ suggestion, onLogged }: TradeSuggestionCardProps) {
  const [evPreview, setEvPreview] = useState<any | null>(null);
  const [evLoading, setEvLoading] = useState(false);
  const [evError, setEvError] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);
  const [logging, setLogging] = useState(false);
  const [paperTrading, setPaperTrading] = useState(false);

  // Normalize symbol/ticker
  const rawSymbol = suggestion.display_symbol || suggestion.symbol || suggestion.ticker || 'UNKNOWN';
  const displaySymbol = suggestion.display_symbol
      || ((suggestion.type === 'option' || rawSymbol.length > 10)
          ? formatOptionDisplay(rawSymbol)
          : rawSymbol);

  const displayStrategy = suggestion.strategy || suggestion.type || 'Trade';
  const displayScore = suggestion.score || 0;
  const badges = suggestion.badges || [];

  const handleEvPreview = async () => {
    try {
      setEvLoading(true);
      setEvError(null);
      const payload = {
        premium: suggestion.price ?? 1.0,
        strike: suggestion.strike_price ?? suggestion.entry_price ?? 100,
        current_price: suggestion.underlying_price ?? suggestion.entry_price ?? 100,
        delta: -0.3,
        strategy: suggestion.strategy ?? 'credit_spread',
        width: suggestion.width ?? 5,
        contracts: 1,
        account_value: undefined,
        max_risk_percent: 2.0,
      };
      const res = await fetch(`${API_URL}/ev`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      });
      if (!res.ok) {
        const errData = await res.json().catch(() => ({}));
        throw new Error(errData.detail || `EV request failed: ${res.status}`);
      }
      const data = await res.json();
      setEvPreview(data);
    } catch (e:any) {
      setEvError(e.message);
      setEvPreview(null);
    } finally {
      setEvLoading(false);
    }
  };

  const copyOrderJson = () => {
    if (suggestion.order_json) {
      navigator.clipboard.writeText(JSON.stringify(suggestion.order_json, null, 2));
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    }
  };

  const buildTicketFromSuggestion = () => {
    const order = suggestion.order_json || {};
    const symbol = suggestion.display_symbol || suggestion.symbol || suggestion.ticker || "UNKNOWN";

    return {
      ticket: {
        ticket_id: undefined,
        source_engine: suggestion.window || "suggestion",
        source_ref_id: suggestion.id,
        strategy_type: suggestion.strategy || suggestion.type || "custom",
        symbol,
        legs: [], // v1: leave empty, backend can infer from order_json if needed later
        order_type: "limit",
        limit_price: typeof order.limit_price === "number" ? order.limit_price : suggestion.price ?? null,
        quantity: order.quantity || order.contracts || 1,
        catalyst_window: suggestion.window,
        conviction_score: suggestion.score ?? undefined,
        expected_value: suggestion.ev ?? suggestion.metrics?.expected_value,
        risk_bracket: undefined,
        regime_context: order.context || {}
      },
      portfolio_id: undefined
    };
  };

  const handlePaperTrade = async () => {
    try {
      setPaperTrading(true);
      const { data: { session } } = await supabase.auth.getSession();
      const headers: Record<string, string> = { "Content-Type": "application/json" };
      if (session) {
        headers["Authorization"] = `Bearer ${session.access_token}`;
      } else {
        headers["X-Test-Mode-User"] = TEST_USER_ID;
      }

      const payload = buildTicketFromSuggestion();
      const res = await fetch(`${API_URL}/paper/execute`, {
        method: "POST",
        headers,
        body: JSON.stringify(payload),
      });

      if (!res.ok) {
        console.error("Failed to execute paper trade", await res.text());
        return;
      }

      // Optional: we could surface a toast/snackbar later; for v1 just log.
      console.log("Paper trade executed", await res.json());
    } catch (err) {
      console.error("Error executing paper trade", err);
    } finally {
      setPaperTrading(false);
    }
  };

  const handleLogTrade = async () => {
    if (!suggestion.id) return;
    try {
      setLogging(true);
      const { data: { session } } = await supabase.auth.getSession();
      const headers: Record<string, string> = { 'Content-Type': 'application/json' };
      if (session) {
        headers['Authorization'] = `Bearer ${session.access_token}`;
      } else {
        headers['X-Test-Mode-User'] = TEST_USER_ID;
      }

      const res = await fetch(`${API_URL}/suggestions/${suggestion.id}/log-trade`, {
        method: 'POST',
        headers,
      });

      if (!res.ok) {
        console.error('Failed to log trade from suggestion', await res.text());
        return;
      }

      if (onLogged) onLogged(suggestion.id);
    } catch (err) {
      console.error('Error logging trade', err);
    } finally {
      setLogging(false);
    }
  };

  const renderMorningContent = () => {
    const order = suggestion.order_json || {};
    const meta = suggestion.sizing_metadata || {};
    return (
      <div className="mt-3 p-3 bg-orange-50 rounded text-xs space-y-1 border border-orange-100">
        <div className="flex justify-between font-bold text-orange-900">
          <span>Limit Price: ${typeof order.limit_price === 'number' ? safeFixed(order.limit_price) : 'N/A'}</span>
          <span>Contracts: {order.legs?.[0]?.quantity || order.quantity || 'N/A'}</span>
        </div>
        {meta.stop_loss && <div>Stop Loss: ${meta.stop_loss}</div>}
        <div className="text-gray-600 mt-1 italic">
          {suggestion.rationale || "Morning limit order opportunity."}
        </div>
        <Button
            variant="outline"
            size="sm"
            onClick={copyOrderJson}
            className="mt-2 w-full h-auto py-1 text-xs flex items-center justify-center gap-2 border-orange-200 text-orange-700 bg-white hover:bg-orange-100 hover:text-orange-800 transition-colors"
        >
          {copied ? <CheckCircle2 className="w-3 h-3" /> : <Copy className="w-3 h-3" />}
          {copied ? 'Copied' : 'Copy Limit Order'}
        </Button>
      </div>
    );
  };

  const renderMiddayContent = () => {
    const order = suggestion.order_json || {};
    const meta = suggestion.sizing_metadata || {};

    // Calculate cash required if available
    const cashRequired = (order.limit_price || 0) * (order.quantity || 0) * 100;

    return (
      <div className="mt-3 p-3 bg-blue-50 rounded text-xs space-y-1 border border-blue-100">
        <div className="grid grid-cols-2 gap-2 text-blue-900 font-medium">
          <div>Entry: ${typeof order.limit_price === 'number' ? safeFixed(order.limit_price) : 'MKT'}</div>
          <div>Size: {order.quantity || 1} contracts</div>
          {meta.target_price && <div>Target: ${meta.target_price}</div>}
          {meta.stop_loss && <div>Stop: ${meta.stop_loss}</div>}
        </div>
        {cashRequired > 0 && (
           <div className="text-gray-500 mt-1">Est. Cash: ${cashRequired.toLocaleString()}</div>
        )}

        <div className="flex gap-2 mt-2">
            <Button
                variant="outline"
                size="sm"
                onClick={copyOrderJson}
                className="flex-1 h-auto py-1 text-xs flex items-center justify-center gap-2 border-blue-200 text-blue-700 bg-white hover:bg-blue-100 hover:text-blue-800 transition-colors"
            >
              {copied ? <CheckCircle2 className="w-3 h-3" /> : <Copy className="w-3 h-3" />}
              {copied ? 'Copied' : 'Copy JSON'}
            </Button>
            <Button
                variant="ghost"
                size="sm"
                onClick={handleEvPreview}
                disabled={evLoading}
                className="flex-1 h-auto py-1 text-xs bg-blue-100 text-blue-700 hover:bg-blue-200 hover:text-blue-800 transition-colors"
            >
                {evLoading ? (
                  <>
                    <Loader2 className="mr-2 h-3 w-3 animate-spin" />
                    Loading...
                  </>
                ) : 'EV Preview'}
            </Button>
        </div>
      </div>
    );
  };

  const evValue = suggestion.ev !== undefined ? suggestion.ev : suggestion.metrics?.expected_value;
  const winRate = suggestion.metrics?.probability_of_profit;

  return (
    <Card className="mb-4 shadow-sm hover:shadow-md transition-shadow">
      <CardContent className="p-4">
        <div className="flex justify-between items-start">
          <div>
            <h4 className="font-bold text-lg">{displaySymbol}</h4>
            <p className="text-sm text-gray-500">{displayStrategy}</p>
          </div>
          <div className="flex flex-col items-end gap-1 text-right">
            {displayScore > 0 && (
              <>
                <div className="text-2xl font-bold text-blue-600">{displayScore}</div>
                <div className="text-xs text-gray-400">OTC Score</div>
              </>
            )}
            <QuantumTooltip
              label="Why this trade?"
              content="Suggested based on your positions, volatility regime, and risk model. Always confirm it fits your own plan."
            />
          </div>
        </div>

        <div className="flex flex-wrap gap-2 my-2 items-center">
          {badges.map((badge: string) => (
             <Badge key={badge} variant="outline">{badge}</Badge>
          ))}

          {/* Always show EV/Win badges if metrics exist */}
          {typeof evValue === 'number' && (
            <Badge className="bg-blue-50 text-blue-700 border border-blue-100">
              EV: ${safeFixed(evValue)}
            </Badge>
          )}
          {typeof winRate === 'number' && (
            <Badge className="bg-purple-50 text-purple-700 border border-purple-100">
              Win: {Math.round(winRate)}%
            </Badge>
          )}
          {(typeof evValue === 'number' || typeof winRate === 'number') && (
            <QuantumTooltip
              label="EV explained"
              content="Expected Value (EV) estimates long-run average profitability if the same trade were repeated many times."
            />
          )}
        </div>

        {/* Conditional Content Based on Window */}
        {suggestion.window === 'morning_limit' ? renderMorningContent() :
         suggestion.window === 'midday_entry' ? renderMiddayContent() : (
           /* Default / Scout View */
           <>
             {suggestion.sizing && (
               <div className="mt-3 p-3 bg-indigo-50 border border-indigo-100 rounded text-xs text-indigo-900">
                 <div className="flex justify-between font-bold mb-1">
                   <span>Rec. Size: {suggestion.sizing.recommended_contracts} contracts</span>
                   <span>EV: {safeFixed(suggestion.sizing.ev_percent, 1)}%</span>
                 </div>
                 <div className="text-[10px] opacity-80 leading-tight">
                   {suggestion.sizing.rationale}
                 </div>
               </div>
             )}

             <p className="text-sm mt-2 text-gray-700">
               {suggestion.rationale}
             </p>

             <Button
               variant="link"
               size="sm"
               onClick={handleEvPreview}
               disabled={evLoading}
               className="mt-3 h-auto p-0 text-xs text-blue-600 hover:no-underline hover:text-blue-700 disabled:opacity-50"
             >
               {evLoading ? <Loader2 className="mr-1 h-3 w-3 animate-spin" /> : null}
               {evLoading ? 'Calculating EV…' : 'EV preview'}
             </Button>
           </>
         )}

        {evPreview && (
          <div className="mt-2 border-t pt-2 text-xs text-gray-600 space-y-1">
            <div>EV: ${safeFixed(evPreview.expected_value)}</div>
            {evPreview.position_sizing && (
              <div>Suggested size: {evPreview.position_sizing.contracts_to_trade} contracts</div>
            )}
            {evError && <div className="text-red-500">{evError}</div>}
          </div>
        )}

        {(suggestion.window === 'morning_limit' || suggestion.window === 'midday_entry') && (
            <div className="mt-3 flex justify-end gap-2">
                <Button
                    variant="outline"
                    size="sm"
                    onClick={handlePaperTrade}
                    disabled={paperTrading}
                    className="h-auto py-1 text-xs border-blue-200 text-blue-700 hover:bg-blue-50 hover:text-blue-800"
                >
                    {paperTrading ? <Loader2 className="mr-2 h-3 w-3 animate-spin" /> : null}
                    {paperTrading ? "Simulating…" : "Paper Trade"}
                </Button>
                <Button
                    variant="outline"
                    size="sm"
                    onClick={handleLogTrade}
                    disabled={logging}
                    className="h-auto py-1 text-xs border-emerald-200 text-emerald-700 hover:bg-emerald-50 hover:text-emerald-800"
                >
                    {logging ? <Loader2 className="mr-2 h-3 w-3 animate-spin" /> : null}
                    {logging ? 'Logging…' : 'Mark Executed (Log Trade)'}
                </Button>
            </div>
        )}
      </CardContent>
    </Card>
  );
}
