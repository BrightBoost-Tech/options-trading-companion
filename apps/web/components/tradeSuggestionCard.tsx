
import React from 'react';
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";

interface TradeSuggestionCardProps {
  trade: {
    symbol: string;
    strategy: string;
    score: number;
    badges: string[];
    rationale: string;
  };
}

const TradeSuggestionCard: React.FC<TradeSuggestionCardProps> = ({ trade }) => {
  return (
    <Card>
      <CardHeader>
        <CardTitle>{trade.symbol} - {trade.strategy}</CardTitle>
      </CardHeader>
      <CardContent>
        <div className="flex justify-between items-center mb-4">
          <div className="text-2xl font-bold">{trade.score}</div>
          <div className="flex space-x-2">
            {trade.badges.map((badge) => (
              <Badge key={badge}>{badge}</Badge>
            ))}
          </div>
        </div>
        <p className="text-sm text-gray-500">{trade.rationale}</p>
      </CardContent>
    </Card>
  );
};

export default TradeSuggestionCard;
