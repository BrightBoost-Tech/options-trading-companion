"use client";

import { Info } from "lucide-react";

interface QuantumTooltipProps {
  content: string;
  label?: string; // optional small label like “Why this trade?”
}

export function QuantumTooltip({ content, label }: QuantumTooltipProps) {
  return (
    <div className="group relative inline-flex items-center gap-1.5 cursor-help">
      {label && (
        <span className="text-xs font-medium text-neutral-400 border-b border-dotted border-neutral-600 group-hover:text-neutral-200 transition-colors">
          {label}
        </span>
      )}
      <Info className="w-3.5 h-3.5 text-neutral-500 group-hover:text-blue-400 transition-colors" />

      {/* Tooltip content */}
      <div className="absolute bottom-full left-1/2 -translate-x-1/2 mb-2 w-64 p-3 bg-neutral-900 border border-neutral-700 rounded-lg shadow-xl opacity-0 invisible group-hover:opacity-100 group-hover:visible transition-all duration-200 z-50 pointer-events-none">
        <p className="text-xs text-neutral-300 leading-relaxed font-normal">
          {content}
        </p>
        <div className="absolute top-full left-1/2 -translate-x-1/2 border-4 border-transparent border-t-neutral-900" />
      </div>
    </div>
  );
}
