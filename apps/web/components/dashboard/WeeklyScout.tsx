'use client';
import { useEffect, useState } from 'react';
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";

export function WeeklyScout() {
  const [ideas, setIdeas] = useState<any[]>([]);

  useEffect(() => {
    fetch('http://127.0.0.1:8000/scout/weekly')
      .then(res => res.json())
      .then(data => setIdeas(data.scout_results || []))
      .catch(err => console.error("Scout failed", err));
  }, []);

  return (
    <Card className="h-full border-l-4 border-l-green-500">
      <CardHeader>
        <CardTitle>Weekly Options Scout</CardTitle>
      </CardHeader>
      <CardContent className="space-y-3">
        {ideas.length === 0 ? (
           <p className="text-muted-foreground text-sm">Scanning market data...</p>
        ) : (
           ideas.map((idea, i) => (
             <div key={i} className="flex justify-between items-center p-2 bg-secondary/40 rounded">
               <div>
                 <div className="font-bold flex items-center gap-2">
                   {idea.symbol}
                   <Badge variant="outline" className="text-[10px]">{idea.strategy}</Badge>
                 </div>
                 <div className="text-xs text-muted-foreground">
                   Score: <span className="text-green-500 font-bold">{idea.alpha_score}</span> | IVR: {idea.iv_rank}
                 </div>
               </div>
               <div className="text-right text-xs">
                 <div className="text-green-400">Target: +${idea.max_gain}</div>
                 <div className="text-red-400">Risk: -${idea.max_loss}</div>
               </div>
             </div>
           ))
        )}
      </CardContent>
    </Card>
  );
}
