'use client';

import React from 'react';
import { Suggestion } from '@/lib/types';
import SuggestionCard from '../dashboard/SuggestionCard';

interface MiddayEntriesListProps {
  suggestions: Suggestion[];
}

export default function MiddayEntriesList({ suggestions }: MiddayEntriesListProps) {
  if (suggestions.length === 0) {
      return (
        <div className="text-center py-10 text-gray-400">
          <p>No midday suggestions.</p>
        </div>
      );
  }

  return (
    <div className="space-y-4">
      {suggestions.map((s, i) => (
         <SuggestionCard
            key={s.id || i}
            suggestion={s}
        />
      ))}
    </div>
  );
}
