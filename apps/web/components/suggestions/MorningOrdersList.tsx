'use client';

import React from 'react';
import { Suggestion } from '@/lib/types';
import SuggestionCard from '../dashboard/SuggestionCard';

interface MorningOrdersListProps {
  suggestions: Suggestion[];
}

export default function MorningOrdersList({ suggestions }: MorningOrdersListProps) {
  if (suggestions.length === 0) {
    return (
      <div className="text-center py-10 text-gray-400">
        <p>No morning suggestions.</p>
      </div>
    );
  }

  return (
    <div className="space-y-4">
      {suggestions.map((s, i) => (
         <SuggestionCard
            key={i}
            suggestion={s}
            // Add default handlers if needed
        />
      ))}
    </div>
  );
}
