"use client";

import React from 'react';
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from '@/components/ui/tooltip';
import { Info } from 'lucide-react';
import { cn } from '@/lib/utils';

interface QuantumTooltipProps {
  content: string;
  label?: string;
  className?: string;
}

export function QuantumTooltip({ content, label, className }: QuantumTooltipProps) {
  return (
    <TooltipProvider>
      <Tooltip>
        <TooltipTrigger asChild>
          <button
            type="button"
            aria-label={label ? undefined : "More information"}
            className={cn(
              "group inline-flex items-center gap-1.5 focus:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 rounded-sm",
              className
            )}
          >
            {label && (
              <span className="text-xs font-medium text-neutral-400 border-b border-dotted border-neutral-600 group-hover:text-neutral-200 transition-colors">
                {label}
              </span>
            )}
            <Info className="w-3.5 h-3.5 text-neutral-500 group-hover:text-blue-400 transition-colors" />
          </button>
        </TooltipTrigger>
        <TooltipContent>
          <p className="max-w-xs text-xs">{content}</p>
        </TooltipContent>
      </Tooltip>
    </TooltipProvider>
  );
}
