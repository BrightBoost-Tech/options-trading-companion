'use client';

import React, { memo } from 'react';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card } from '@/components/ui/card';
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
    <Card className="p-4 flex flex-col gap-3">
      {/* Header: Action & Symbol */}
      <div className="flex justify-between items-start">
        <div className="flex items-center gap-2">
          <Badge className={`${trade.side === 'buy' ? 'bg-emerald-100 text-emerald-800 dark:bg-emerald-900/30 dark:text-emerald-400' : 'bg-rose-100 text-rose-800 dark:bg-rose-900/30 dark:text-rose-400'} border-none`}>
            {trade.side?.toUpperCase()}
          </Badge>
          <div>
            <span className="font-bold text-foreground block">{trade.display_symbol || trade.ticker || trade.symbol}</span>
            <span className="text-xs text-muted-foreground">{trade.strategy || trade.spread_type}</span>
          </div>
        </div>
        <div className="text-right">
          <div className="text-sm font-semibold text-foreground">
            {trade.limit_price ? `$${trade.limit_price.toFixed(2)}` : 'MKT'}
          </div>
          {trade.target_allocation && (
            <div className="text-xs text-blue-600 dark:text-blue-400">Target: {(trade.target_allocation * 100).toFixed(1)}%</div>
          )}
        </div>
      </div>

      {/* Rationale */}
      <div className="bg-muted p-2 rounded text-xs text-muted-foreground italic">
        {trade.notes || trade.reason}
      </div>

      {/* Details: Delta, Debit/Credit */}
      <div className="flex gap-4 text-xs text-muted-foreground">
        <div>Qty: <span className="font-medium text-foreground">{trade.quantity}</span></div>
        {trade.current_allocation !== undefined && (
          <div>Current: <span className="font-medium text-foreground">{(trade.current_allocation * 100).toFixed(1)}%</span></div>
        )}
      </div>

      {/* Actions */}
      <div className="flex gap-2 mt-1">
        <TooltipProvider>
          <Tooltip>
            <TooltipTrigger asChild>
              <span className="w-full cursor-not-allowed" tabIndex={0} aria-label="Apply Rebalance (Disabled: Automated execution coming soon)">
                <Button size="sm" className="w-full" disabled>
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
              <span className="w-full cursor-not-allowed" tabIndex={0} aria-label="Execute in Robinhood (Disabled: Integration pending)">
                <Button size="sm" variant="outline" className="w-full text-muted-foreground" disabled>
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
    </Card>
  );
};

export default memo(OptimizerSuggestionCard);
