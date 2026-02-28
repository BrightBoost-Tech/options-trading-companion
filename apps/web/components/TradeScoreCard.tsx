'use client';

import { useState, useEffect, useCallback } from 'react';
import { API_URL } from '@/lib/constants';
import { Progress } from '@/components/ui/progress';

interface EVMetrics {
  expected_value: number;
  win_probability: number;
  loss_probability: number;
  max_gain: number;
  max_loss: number;
  risk_reward_ratio_str?: string;
  trade_cost: number;
  breakeven_price?: number;
  position_sizing?: {
    contracts_to_trade: number;
    risk_per_trade_usd: number;
  };
}

interface UseTradeScoreProps {
  premium: number;
  strike: number;
  currentPrice: number;
  delta: number;
  strategy: any;
  width?: number;
  contracts?: number;
  accountValue?: number;
}

// Hook to calculate trade score
export const useTradeScore = ({
  premium,
  strike,
  currentPrice,
  delta,
  strategy,
  width,
  contracts = 1,
  accountValue,
}: UseTradeScoreProps) => {
  const [metrics, setMetrics] = useState<EVMetrics | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const calculateScore = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const response = await fetch(`${API_URL}/ev`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          premium,
          strike,
          current_price: currentPrice,
          delta,
          strategy,
          width,
          contracts,
          account_value: accountValue,
          max_risk_percent: 2.0, // Default 2% risk
        }),
      });

      if (!response.ok) {
        const errData = await response.json();
        throw new Error(errData.detail || 'Failed to calculate EV');
      }

      const data: EVMetrics = await response.json();
      setMetrics(data);
    } catch (err: any) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  }, [premium, strike, currentPrice, delta, strategy, width, contracts, accountValue]);

  useEffect(() => {
    if (premium && strike && currentPrice && delta && strategy) {
      calculateScore();
    }
  }, [calculateScore, premium, strike, currentPrice, delta, strategy]);

  return { metrics, loading, error };
};

// --- Helper Functions ---
const getScoreAndColor = (ev: number, maxLoss: number) => {
  if (maxLoss <= 0) { // Positive EV on risk-free trade is great
    return { score: 95, color: 'bg-green-500', progressColor: '[&>div]:bg-green-500', label: 'Excellent' };
  }

  const evToRiskRatio = (ev / maxLoss) * 100;

  if (evToRiskRatio >= 25) {
    return { score: 90, color: 'bg-green-500', progressColor: '[&>div]:bg-green-500', label: 'Excellent' };
  } else if (evToRiskRatio >= 15) {
    return { score: 75, color: 'bg-yellow-500', progressColor: '[&>div]:bg-yellow-500', label: 'Good' };
  } else if (evToRiskRatio >= 5) {
    return { score: 60, color: 'bg-yellow-400', progressColor: '[&>div]:bg-yellow-400', label: 'Fair' };
  } else {
    return { score: 40, color: 'bg-red-500', progressColor: '[&>div]:bg-red-500', label: 'Poor' };
  }
};


interface TradeScoreCardProps {
  symbol: string;
  strategy: string;
  metrics: EVMetrics;
  onExecute: () => void;
  onAddToWatchlist: () => void;
}

export const TradeScoreCard = ({
  symbol,
  strategy,
  metrics,
  onExecute,
  onAddToWatchlist,
}: TradeScoreCardProps) => {
  const {
    expected_value,
    win_probability,
    max_gain,
    max_loss,
    risk_reward_ratio_str,
    position_sizing,
  } = metrics;

  const { score, color, progressColor, label } = getScoreAndColor(expected_value, max_loss);

  return (
    <div className="bg-white rounded-lg shadow-md border border-gray-200 p-4 w-full">
      {/* Header */}
      <div className="flex justify-between items-start mb-3">
        <div>
          <h3 className="text-lg font-bold text-gray-900">{symbol}</h3>
          <p className="text-sm text-gray-600">{strategy}</p>
        </div>
        <div className="text-right">
          <div className="flex items-center gap-2">
            <span className={`text-sm font-semibold px-2 py-1 rounded ${color} text-white`}>{label}</span>
          </div>
        </div>
      </div>

      {/* Score Meter */}
      <div className="mb-4">
          <Progress
            value={score}
            aria-label="Trade Score Confidence"
            className={`h-2.5 bg-gray-200 ${progressColor}`}
          />
          <p className="text-xs text-center mt-1 text-gray-600" aria-hidden="true">
            Trade Score: {score}/100
          </p>
      </div>

      {/* Key Metrics */}
      <div className="grid grid-cols-2 gap-3 text-sm mb-4">
        <Metric label="Expected Value (EV)" value={`$${expected_value.toFixed(2)}`} isPositive={expected_value >= 0} />
        <Metric label="Win Probability" value={`${(win_probability * 100).toFixed(0)}%`} />
        <Metric label="Max Gain" value={`$${max_gain.toFixed(0)}`} isPositive={true} />
        <Metric label="Max Loss" value={`$${max_loss.toFixed(0)}`} isPositive={false} />
        <Metric label="Risk/Reward" value={risk_reward_ratio_str || 'N/A'} />
        {position_sizing && (
          <Metric label="Suggested Size" value={`${position_sizing.contracts_to_trade} Contracts`} />
        )}
      </div>

      {/* Action Buttons */}
      <div className="flex gap-3">
        <button
          onClick={onExecute}
          aria-label={`Execute trade for ${symbol}`}
          className="flex-1 bg-blue-600 text-white font-semibold py-2 px-4 rounded-lg hover:bg-blue-700 transition focus-visible:ring-2 focus-visible:ring-offset-2 focus-visible:ring-blue-600 outline-none"
        >
          Execute
        </button>
        <button
          onClick={onAddToWatchlist}
          aria-label={`Add ${symbol} to watchlist`}
          className="flex-1 bg-gray-200 text-gray-800 font-semibold py-2 px-4 rounded-lg hover:bg-gray-300 transition focus-visible:ring-2 focus-visible:ring-offset-2 focus-visible:ring-gray-400 outline-none"
        >
          Watchlist
        </button>
      </div>
    </div>
  );
};

const Metric = ({ label, value, isPositive }: { label: string; value: string; isPositive?: boolean }) => (
  <div className="bg-gray-50 p-2 rounded-lg border border-gray-200">
    <p className="text-xs text-gray-500">{label}</p>
    <p className={`font-bold text-base ${isPositive === true ? 'text-green-600' : isPositive === false ? 'text-red-600' : 'text-gray-900'}`}>
      {value}
    </p>
  </div>
);
