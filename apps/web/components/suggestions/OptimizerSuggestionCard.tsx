'use client';

import React, { memo } from 'react';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from '@/components/ui/tooltip';

interface OptimizerSuggestionCardProps {
  trade: any;
}

const OptimizerSuggestionCard = ({ trade }: OptimizerSuggestionCardProps) => {
  return (
    <div className="bg-white p-4 rounded-lg border border-gray-200 shadow-sm flex flex-col gap-3">
      {/* Header: Action & Symbol */}
      <div className="flex justify-between items-start">
        <div className="flex items-center gap-2">
          <Badge className={`${trade.side === 'buy' ? 'bg-green-100 text-green-800' : 'bg-red-100 text-red-800'} border-none`}>
            {trade.side?.toUpperCase()}
          </Badge>
          <div>
            <span className="font-bold text-gray-900 block">{trade.display_symbol || trade.ticker || trade.symbol}</span>
            <span className="text-xs text-gray-500">{trade.strategy || trade.spread_type}</span>
          </div>
        </div>
        <div className="text-right">
          <div className="text-sm font-semibold text-gray-900">
            {trade.limit_price ? `$${trade.limit_price.toFixed(2)}` : 'MKT'}
          </div>
          {trade.target_allocation && (
            <div className="text-xs text-blue-600">Target: {(trade.target_allocation * 100).toFixed(1)}%</div>
          )}
        </div>
      </div>

      {/* Rationale */}
      <div className="bg-gray-50 p-2 rounded text-xs text-gray-600 italic">
        {trade.notes || trade.reason}
      </div>

      {/* Details: Delta, Debit/Credit */}
      <div className="flex gap-4 text-xs text-gray-500">
        <div>Qty: <span className="font-medium text-gray-900">{trade.quantity}</span></div>
        {trade.current_allocation !== undefined && (
          <div>Current: <span className="font-medium text-gray-900">{(trade.current_allocation * 100).toFixed(1)}%</span></div>
        )}
      </div>

      {/* Actions */}
      <div className="flex gap-2 mt-1">
        <TooltipProvider>
          <Tooltip>
            <TooltipTrigger asChild>
              <span className="w-full" tabIndex={0}>
                <Button size="sm" className="w-full bg-indigo-600 hover:bg-indigo-700 text-white pointer-events-none" disabled>
                  Apply Rebalance
                </Button>
              </span>
            </TooltipTrigger>
            <TooltipContent>
              <p>Automated execution coming soon</p>
            </TooltipContent>
          </Tooltip>
        </TooltipProvider>

        <TooltipProvider>
          <Tooltip>
            <TooltipTrigger asChild>
              <span className="w-full" tabIndex={0}>
                <Button size="sm" variant="outline" className="w-full text-gray-600 pointer-events-none" disabled>
                  Execute in Robinhood
                </Button>
              </span>
            </TooltipTrigger>
            <TooltipContent>
              <p>Integration pending</p>
            </TooltipContent>
          </Tooltip>
        </TooltipProvider>
      </div>
    </div>
  );
};

export default memo(OptimizerSuggestionCard);
