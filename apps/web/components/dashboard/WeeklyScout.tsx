'use client';
import { useEffect, useState } from 'react';
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogTrigger } from "@/components/ui/dialog";
import { ArrowRight, BrainCircuit } from 'lucide-react';

export function WeeklyScout() {
  const [ideas, setIdeas] = useState<any[]>([]);

  useEffect(() => {
    fetch('http://127.0.0.1:8000/scout/weekly')
      .then(res => res.json())
      .then(data => setIdeas(data.scout_results || []))
      .catch(err => console.error(err));
  }, []);

  return (
    <Card className="h-full border-l-4 border-l-green-500 bg-gradient-to-br from-background to-secondary/10">
      <CardHeader className="flex flex-row items-center justify-between pb-2">
        <CardTitle className="flex items-center gap-2">
          <BrainCircuit className="h-5 w-5 text-green-500" />
          Weekly Options Scout
        </CardTitle>
        <Badge variant="outline" className="text-xs">AI Ranked</Badge>
      </CardHeader>

      <CardContent className="space-y-3">
        {ideas.map((idea, i) => (
          <Dialog key={i}>
            <DialogTrigger asChild>
              <div className="group flex justify-between items-center p-3 bg-card border rounded-lg cursor-pointer hover:border-green-500/50 transition-all">
                <div>
                  <div className="font-bold flex items-center gap-2">
                    {idea.symbol}
                    <span className="text-[10px] uppercase text-muted-foreground font-normal tracking-wider">{idea.strategy}</span>
                  </div>
                  <div className="text-xs text-muted-foreground mt-1">
                    Score: <span className="text-green-500 font-bold">{idea.alpha_score}</span>
                    <span className="mx-2">•</span>
                    Win Probability: {(idea.prob_profit * 100).toFixed(0)}%
                  </div>
                </div>
                <ArrowRight className="h-4 w-4 text-muted-foreground group-hover:text-green-500 group-hover:translate-x-1 transition-all" />
              </div>
            </DialogTrigger>

            <DialogContent>
              <DialogHeader>
                <DialogTitle className="flex items-center gap-2">
                  Trade Analysis: {idea.symbol}
                  <Badge>{idea.strategy}</Badge>
                </DialogTitle>
              </DialogHeader>

              <div className="space-y-4 py-4">
                {/* 1. Thesis */}
                <div className="p-3 bg-secondary/50 rounded-md border border-l-4 border-l-primary">
                  <h4 className="text-sm font-semibold mb-1">AI Thesis</h4>
                  <p className="text-sm text-muted-foreground">{idea.thesis}</p>
                </div>

                {/* 2. Risk/Reward Stats */}
                <div className="grid grid-cols-3 gap-4">
                  <div className="text-center p-2 bg-secondary rounded">
                    <div className="text-xs text-muted-foreground">Max Gain</div>
                    <div className="text-green-500 font-mono font-bold">${idea.max_gain}</div>
                  </div>
                  <div className="text-center p-2 bg-secondary rounded">
                    <div className="text-xs text-muted-foreground">Max Loss</div>
                    <div className="text-red-500 font-mono font-bold">${idea.max_loss}</div>
                  </div>
                   <div className="text-center p-2 bg-secondary rounded">
                    <div className="text-xs text-muted-foreground">IV Rank</div>
                    <div className="text-yellow-500 font-mono font-bold">{idea.iv_rank}</div>
                  </div>
                </div>

                {/* 3. Action */}
                <Button className="w-full font-bold">
                  Stage Trade in Journal
                </Button>
              </div>
            </DialogContent>
          </Dialog>
        ))}
      </CardContent>
    </Card>
  );
}