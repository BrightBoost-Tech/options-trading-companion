'use client';

import { useEffect, useState } from 'react';
import { supabase } from '@/lib/supabase';
import { Holding } from "@/types";

export default function PortfolioHoldingsTable() {
  const [holdings, setHoldings] = useState<Holding[] | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    fetchHoldings();
  }, []);

  const fetchHoldings = async () => {
    setLoading(true);
    try {
      const { data, error } = await supabase
        .from("holdings")
        .select('*')
        .order('symbol', { ascending: true });

      if (error) throw error;
      setHoldings(data || []);
    } catch (error) {
      console.error('Error loading holdings:', error);
    } finally {
      setLoading(false);
    }
  };

  if (loading) {
    return <div className="p-4 text-gray-400">Loading holdings...</div>;
  }

  if (!holdings || holdings.length === 0) {
    return (
      <div className="p-8 text-center border border-gray-800 rounded-lg bg-gray-900/50">
        <p className="text-gray-400">No holdings found.</p>
        <p className="text-sm text-gray-500 mt-2">Connect your broker and click "Sync Holdings".</p>
      </div>
    );
  }

  return (
    <div className="overflow-x-auto border border-gray-800 rounded-lg shadow-sm">
      <table className="min-w-full divide-y divide-gray-800 bg-gray-900">
        <thead className="bg-gray-800">
          <tr>
            <th className="px-6 py-3 text-left text-xs font-medium text-gray-400 uppercase tracking-wider">Symbol</th>
            <th className="px-6 py-3 text-right text-xs font-medium text-gray-400 uppercase tracking-wider">Qty</th>
            <th className="px-6 py-3 text-right text-xs font-medium text-gray-400 uppercase tracking-wider">Price</th>
            <th className="px-6 py-3 text-right text-xs font-medium text-gray-400 uppercase tracking-wider">Cost Basis</th>
            <th className="px-6 py-3 text-right text-xs font-medium text-gray-400 uppercase tracking-wider">Total Value</th>
            <th className="px-6 py-3 text-right text-xs font-medium text-gray-400 uppercase tracking-wider">Gain/Loss</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-gray-800">
          {holdings.map((h: Holding) => {
            const totalValue = h.quantity * h.current_price;
            const costBasis = h.cost_basis || 0;
            const totalCost = h.quantity * costBasis;
            const gainLoss = costBasis > 0 ? totalValue - totalCost : 0;
            const gainLossPercent = costBasis > 0 ? (gainLoss / totalCost) * 100 : 0;
            const isProfitable = gainLoss >= 0;

            return ( // Using symbol as key, assuming it's unique per user portfolio
              <tr key={h.symbol} className="hover:bg-gray-800/50 transition-colors">
                <td className="px-6 py-4 whitespace-nowrap text-sm font-medium text-white">
                  {h.symbol}
                </td>
                <td className="px-6 py-4 whitespace-nowrap text-sm text-right text-gray-300">
                  {h.quantity.toFixed(2)}
                </td>
                <td className="px-6 py-4 whitespace-nowrap text-sm text-right text-gray-300">
                  ${h.current_price.toFixed(2)}
                </td>
                <td className="px-6 py-4 whitespace-nowrap text-sm text-right text-gray-400">
                  {costBasis > 0 ? `$${costBasis.toFixed(2)}` : '-'}
                </td>
                <td className="px-6 py-4 whitespace-nowrap text-sm text-right text-white font-medium">
                  {`$${totalValue.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`}
                </td>
                <td className={`px-6 py-4 whitespace-nowrap text-sm text-right font-medium ${isProfitable ? 'text-green-400' : 'text-red-400'}`}>
                  {costBasis > 0 ? (
                    <span>
                      {isProfitable ? '+' : ''}{gainLoss.toFixed(2)} ({isProfitable ? '+' : ''}{gainLossPercent.toFixed(2)}%)
                    </span>
                  ) : '-'}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
