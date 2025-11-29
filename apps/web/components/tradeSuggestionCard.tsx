import React, { useState } from 'react';
import { Card, CardContent } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { API_URL } from '@/lib/constants';

interface TradeSuggestionMetrics {
  expected_value?: number;
  probability_of_profit?: number; // 0–100
}

interface TradeSuggestion {
  symbol: string;
  strategy?: string;
  type?: string;
  score: number;
  badges: string[];
  rationale: string;
  metrics?: TradeSuggestionMetrics;
  price?: number;
  strike_price?: number;
  entry_price?: number;
  underlying_price?: number;
  width?: number;
}

interface TradeSuggestionCardProps {
  suggestion: TradeSuggestion;
}

export default function TradeSuggestionCard({ suggestion }: TradeSuggestionCardProps) {
  const [evPreview, setEvPreview] = useState<any | null>(null);
  const [evLoading, setEvLoading] = useState(false);
  const [evError, setEvError] = useState<string | null>(null);

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

  return (
    <Card className="mb-4 shadow-sm hover:shadow-md transition-shadow">
      <CardContent className="p-4">
        <div className="flex justify-between items-start">
          <div>
            <h4 className="font-bold text-lg">{suggestion.symbol}</h4>
            <p className="text-sm text-gray-500">{suggestion.strategy || suggestion.type || 'Trade'}</p>
          </div>
          <div className="text-right">
            <div className="text-2xl font-bold text-blue-600">{suggestion.score}</div>
            <div className="text-xs text-gray-400">OTC Score</div>
          </div>
        </div>

        <div className="flex flex-wrap gap-2 my-2">
          {suggestion.badges.map((badge: string) => (
             <Badge key={badge} variant="outline">{badge}</Badge>
          ))}
        </div>

        {suggestion.metrics && (
          <div className="mt-2 flex gap-2 text-xs">
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
          </div>
        )}

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
