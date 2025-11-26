'use client';

import { useEffect, useState } from 'react';
import { createClientComponentClient } from '@supabase/auth-helpers-nextjs';
import { PortfolioHeader } from '@/components/portfolio/PortfolioHeader';
import { DataTable } from '@/components/portfolio/data-table'; // Ensure this file exists
import { columns } from '@/components/portfolio/columns'; // Define your columns here
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';
import { Button } from '@/components/ui/button';
import { RefreshCw } from 'lucide-react';

export default function PortfolioPage() {
  const [positions, setPositions] = useState<any[]>([]);
  const [metrics, setMetrics] = useState({
    totalDelta: 0,
    totalTheta: 0,
    netLiquidity: 0,
    buyingPower: 0
  });
  const [loading, setLoading] = useState(true);
  const supabase = createClientComponentClient();

  const fetchPortfolio = async () => {
    setLoading(true);
    // 1. Fetch Positions
    const { data: posData } = await supabase.from('positions').select('*');

    if (posData) {
      setPositions(posData);

      // 2. Calculate Aggregated Metrics (The "Efficient" Logic)
      // In a real app, these greeks would come from the database/API
      const totalDelta = posData.reduce((acc, p) => acc + (p.greeks?.delta || 0), 0);
      const totalTheta = posData.reduce((acc, p) => acc + (p.greeks?.theta || 0), 0);
      const netLiq = posData.reduce((acc, p) => acc + (p.quantity * p.current_price), 0); // Simplified

      setMetrics({
        totalDelta,
        totalTheta,
        netLiquidity: netLiq,
        buyingPower: 10000 // Mock or fetch from User table
      });
    }
    setLoading(false);
  };

  useEffect(() => {
    fetchPortfolio();
  }, []);

  return (
    <div className="flex-1 space-y-4 p-8 pt-6">
      <div className="flex items-center justify-between space-y-2">
        <h2 className="text-3xl font-bold tracking-tight">Portfolio</h2>
        <div className="flex items-center space-x-2">
          <Button onClick={fetchPortfolio} disabled={loading}>
            <RefreshCw className={`mr-2 h-4 w-4 ${loading ? 'animate-spin' : ''}`} />
            Sync
          </Button>
        </div>
      </div>

      {/* 1. High-Level Metrics */}
      <PortfolioHeader metrics={metrics} />

      {/* 2. Optimized Tabbed View */}
      <Tabs defaultValue="options" className="space-y-4">
        <TabsList>
          <TabsTrigger value="options">Option Plays</TabsTrigger>
          <TabsTrigger value="stocks">Long Term Holds</TabsTrigger>
          <TabsTrigger value="all">All Positions</TabsTrigger>
        </TabsList>

        <TabsContent value="options" className="space-y-4">
           {/* Filter logic happens here or in the DataTable */}
           <DataTable columns={columns} data={positions.filter(p => p.asset_class === 'option')} />
        </TabsContent>

        <TabsContent value="stocks" className="space-y-4">
           <DataTable columns={columns} data={positions.filter(p => p.asset_class === 'equity')} />
        </TabsContent>

        <TabsContent value="all" className="space-y-4">
           <DataTable columns={columns} data={positions} />
        </TabsContent>
      </Tabs>
    </div>
  );
}