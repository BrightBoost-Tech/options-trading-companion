import React, { useState } from 'react';
import { Card, CardContent } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { API_URL } from '@/lib/constants';
import { Copy, CheckCircle2 } from 'lucide-react';

interface TradeSuggestionMetrics {
  expected_value?: number;
  probability_of_profit?: number; // 0–100
}

interface TradeSuggestion {
  symbol?: string;
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
}

interface TradeSuggestionCardProps {
  suggestion: TradeSuggestion;
}

export default function TradeSuggestionCard({ suggestion }: TradeSuggestionCardProps) {
  const [evPreview, setEvPreview] = useState<any | null>(null);
  const [evLoading, setEvLoading] = useState(false);
  const [evError, setEvError] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);

  // Normalize symbol/ticker
  const displaySymbol = suggestion.symbol || suggestion.ticker || 'UNKNOWN';
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

  const renderMorningContent = () => {
    const order = suggestion.order_json || {};
    const meta = suggestion.sizing_metadata || {};
    return (
      <div className="mt-3 p-3 bg-orange-50 rounded text-xs space-y-1 border border-orange-100">
        <div className="flex justify-between font-bold text-orange-900">
          <span>Limit Price: ${order.limit_price?.toFixed(2) || 'N/A'}</span>
          <span>Contracts: {order.quantity || 'N/A'}</span>
        </div>
        {meta.stop_loss && <div>Stop Loss: ${meta.stop_loss}</div>}
        <div className="text-gray-600 mt-1 italic">
          {suggestion.rationale || "Morning limit order opportunity."}
        </div>
        <button
            onClick={copyOrderJson}
            className="mt-2 w-full flex items-center justify-center gap-2 bg-white border border-orange-200 text-orange-700 py-1 rounded hover:bg-orange-100 transition-colors"
        >
          {copied ? <CheckCircle2 className="w-3 h-3" /> : <Copy className="w-3 h-3" />}
          {copied ? 'Copied' : 'Copy Limit Order'}
        </button>
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
          <div>Entry: ${order.limit_price?.toFixed(2) || 'MKT'}</div>
          <div>Size: {order.quantity || 1} contracts</div>
          {meta.target_price && <div>Target: ${meta.target_price}</div>}
          {meta.stop_loss && <div>Stop: ${meta.stop_loss}</div>}
        </div>
        {cashRequired > 0 && (
           <div className="text-gray-500 mt-1">Est. Cash: ${cashRequired.toLocaleString()}</div>
        )}

        <div className="flex gap-2 mt-2">
            <button
                onClick={copyOrderJson}
                className="flex-1 flex items-center justify-center gap-2 bg-white border border-blue-200 text-blue-700 py-1 rounded hover:bg-blue-100 transition-colors"
            >
              {copied ? <CheckCircle2 className="w-3 h-3" /> : <Copy className="w-3 h-3" />}
              {copied ? 'Copied' : 'Copy JSON'}
            </button>
            <button
                onClick={handleEvPreview}
                disabled={evLoading}
                className="flex-1 bg-blue-100 text-blue-700 py-1 rounded hover:bg-blue-200 transition-colors disabled:opacity-50"
            >
                {evLoading ? 'Loading...' : 'EV Preview'}
            </button>
        </div>
      </div>
    );
  };

  return (
    <Card className="mb-4 shadow-sm hover:shadow-md transition-shadow">
      <CardContent className="p-4">
        <div className="flex justify-between items-start">
          <div>
            <h4 className="font-bold text-lg">{displaySymbol}</h4>
            <p className="text-sm text-gray-500">{displayStrategy}</p>
          </div>
          <div className="text-right">
            <div className="text-2xl font-bold text-blue-600">{displayScore}</div>
            <div className="text-xs text-gray-400">OTC Score</div>
          </div>
        </div>

        <div className="flex flex-wrap gap-2 my-2">
          {badges.map((badge: string) => (
             <Badge key={badge} variant="outline">{badge}</Badge>
          ))}

          {/* Always show EV/Win badges if metrics exist */}
          {suggestion.metrics && (
            <>
              {suggestion.metrics.expected_value !== undefined && (
                <Badge className="bg-blue-50 text-blue-700 border border-blue-100">
                  EV: ${suggestion.metrics.expected_value.toFixed(2)}
                </Badge>
              )}
              {suggestion.metrics.probability_of_profit !== undefined && (
                <Badge className="bg-purple-50 text-purple-700 border border-purple-100">
                  Win: {Math.round(suggestion.metrics.probability_of_profit)}%
                </Badge>
              )}
            </>
          )}
        </div>

        {/* Conditional Content Based on Window */}
        {suggestion.window === 'morning_limit' ? renderMorningContent() :
         suggestion.window === 'midday_entry' ? renderMiddayContent() : (
           /* Default / Scout View */
           <>
             <p className="text-sm mt-2 text-gray-700">
               {suggestion.rationale}
             </p>

             <button
               onClick={handleEvPreview}
               disabled={evLoading}
               className="mt-3 text-xs text-blue-600 hover:underline disabled:opacity-50"
             >
               {evLoading ? 'Calculating EV…' : 'EV preview'}
             </button>
           </>
         )}

        {evPreview && (
          <div className="mt-2 border-t pt-2 text-xs text-gray-600 space-y-1">
            <div>EV: ${evPreview.expected_value?.toFixed(2)}</div>
            {evPreview.position_sizing && (
              <div>Suggested size: {evPreview.position_sizing.contracts_to_trade} contracts</div>
            )}
            {evError && <div className="text-red-500">{evError}</div>}
          </div>
        )}
      </CardContent>
    </Card>
  );
}
