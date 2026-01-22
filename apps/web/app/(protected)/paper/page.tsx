"use client"

import { useEffect, useState } from "react"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { Button } from "@/components/ui/button"
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table"
import { Badge } from "@/components/ui/badge"
import { Loader2, RefreshCw, TrendingUp, DollarSign, Wallet, AlertCircle } from "lucide-react"
import { fetchWithAuth, ApiError } from "@/lib/api"
import { ClosePaperPositionModal } from "@/components/paper/ClosePaperPositionModal"
import { ResetPaperAccountModal } from "@/components/paper/ResetPaperAccountModal"
import DashboardLayout from "@/components/DashboardLayout"
import { useStrategyRegistry } from "@/hooks/useStrategyRegistry"
import { RequireAuth } from "@/components/RequireAuth"
import { AuthRequired } from "@/components/AuthRequired"

// Types matching backend response
interface PaperPortfolio {
  id: string
  user_id: string
  name: string
  cash_balance: number
  net_liq: number
  created_at: string
}

interface PaperPosition {
  id: string
  portfolio_id: string
  symbol: string
  strategy_key: string
  quantity: number
  avg_entry_price: number
  current_mark: number
  unrealized_pl: number
  created_at: string
}

interface PaperStats {
  total_unrealized_pl: number
  open_positions_count: number
  spy_return_pct: number
  zero_strategy_return_pct: number
}

interface PaperResponse {
  portfolio: PaperPortfolio | null
  positions: PaperPosition[]
  stats: PaperStats
}

export default function PaperTradingPage() {
  const [loading, setLoading] = useState(true)
  const [data, setData] = useState<PaperResponse | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [authMissing, setAuthMissing] = useState(false)

  // Close Modal State
  const [selectedPosition, setSelectedPosition] = useState<PaperPosition | null>(null)
  const [isCloseModalOpen, setIsCloseModalOpen] = useState(false)

  // Reset State
  const [isResetModalOpen, setIsResetModalOpen] = useState(false)
  const [isResetting, setIsResetting] = useState(false)

  const { getMetadata } = useStrategyRegistry();

  const loadData = async () => {
    setLoading(true)
    setError(null)
    try {
      const res = await fetchWithAuth("/paper/portfolio")
      if (res) {
        setData(res)
      } else {
        // Handle empty or error
        setError("Failed to load portfolio data")
      }
    } catch (err) {
      if (err instanceof ApiError && err.status === 401) {
        setAuthMissing(true)
        return
      }
      setError("An error occurred while fetching data")
      console.error(err)
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    loadData()
  }, [])

  const handleClosePosition = (position: PaperPosition) => {
    setSelectedPosition(position)
    setIsCloseModalOpen(true)
  }

  const confirmClosePosition = async (positionId: string) => {
    try {
      await fetchWithAuth("/paper/close", {
        method: "POST",
        body: JSON.stringify({ position_id: positionId }),
      })
      // Refresh data
      await loadData()
    } catch (err) {
      console.error("Failed to close position", err)
      throw err // Let modal handle error display
    }
  }

  const handleResetPortfolio = async () => {
    setIsResetting(true)
    try {
      await fetchWithAuth("/paper/reset", { method: "POST" })
      await loadData()
      setIsResetModalOpen(false)
    } catch (err) {
      console.error("Failed to reset portfolio", err)
      alert("Failed to reset portfolio")
    } finally {
      setIsResetting(false)
    }
  }

  // Show auth required UI if authentication is missing
  if (authMissing) {
    return (
      <DashboardLayout>
        <AuthRequired message="Please log in to access paper trading." />
      </DashboardLayout>
    )
  }

  if (loading && !data) {
    return (
      <DashboardLayout>
        <div className="flex h-[50vh] items-center justify-center">
          <Loader2 className="h-8 w-8 animate-spin text-muted-foreground" />
        </div>
      </DashboardLayout>
    )
  }

  return (
    <RequireAuth>
    <DashboardLayout>
      <div className="space-y-6 p-6">
        <div className="flex items-center justify-between">
          <div>
            <h1 className="text-3xl font-bold tracking-tight">Paper Trading Simulation</h1>
            <p className="text-muted-foreground">Test strategies with virtual capital.</p>
          </div>
          <div className="flex items-center gap-2">
            <Button variant="outline" size="sm" onClick={loadData} disabled={loading}>
              <RefreshCw className={`mr-2 h-4 w-4 ${loading ? "animate-spin" : ""}`} />
              Refresh
            </Button>
            <Button variant="destructive" size="sm" onClick={() => setIsResetModalOpen(true)} disabled={isResetting}>
              {isResetting ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : <AlertCircle className="mr-2 h-4 w-4" />}
              Reset Account
            </Button>
          </div>
        </div>

        {/* Metrics Cards */}
        <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-4">
          <Card>
            <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
              <CardTitle className="text-sm font-medium">Net Liquidity</CardTitle>
              <DollarSign className="h-4 w-4 text-muted-foreground" />
            </CardHeader>
            <CardContent>
              <div className="text-2xl font-bold">
                ${data?.portfolio?.net_liq?.toLocaleString() || "0.00"}
              </div>
              <p className="text-xs text-muted-foreground">
                Total account value
              </p>
            </CardContent>
          </Card>
          <Card>
            <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
              <CardTitle className="text-sm font-medium">Cash Balance</CardTitle>
              <Wallet className="h-4 w-4 text-muted-foreground" />
            </CardHeader>
            <CardContent>
              <div className="text-2xl font-bold">
                ${data?.portfolio?.cash_balance?.toLocaleString() || "0.00"}
              </div>
              <p className="text-xs text-muted-foreground">
                Buying power available
              </p>
            </CardContent>
          </Card>
          <Card>
            <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
              <CardTitle className="text-sm font-medium">Unrealized P/L</CardTitle>
              <TrendingUp className="h-4 w-4 text-muted-foreground" />
            </CardHeader>
            <CardContent>
              <div className={`text-2xl font-bold ${data?.stats?.total_unrealized_pl && data.stats.total_unrealized_pl >= 0 ? "text-green-500" : "text-red-500"}`}>
                {data?.stats?.total_unrealized_pl && data.stats.total_unrealized_pl >= 0 ? "+" : ""}
                ${data?.stats?.total_unrealized_pl?.toFixed(2) || "0.00"}
              </div>
              <p className="text-xs text-muted-foreground">
                Open positions performance
              </p>
            </CardContent>
          </Card>
           <Card>
            <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
              <CardTitle className="text-sm font-medium">Benchmarks</CardTitle>
              <TrendingUp className="h-4 w-4 text-muted-foreground" />
            </CardHeader>
            <CardContent>
              <div className="text-sm space-y-1">
                 <div className="flex justify-between">
                     <span className="text-muted-foreground">Risk-Free:</span>
                     <span className="font-mono">{data?.stats?.zero_strategy_return_pct?.toFixed(2)}%</span>
                 </div>
                 <div className="flex justify-between">
                     <span className="text-muted-foreground">SPY Return:</span>
                     <span className="font-mono">{data?.stats?.spy_return_pct?.toFixed(2)}%</span>
                 </div>
              </div>
            </CardContent>
          </Card>
        </div>

        {/* Positions Table */}
        <Card>
          <CardHeader>
            <CardTitle>Open Positions</CardTitle>
            <CardDescription>
              Manage your active paper trades.
            </CardDescription>
          </CardHeader>
          <CardContent>
            {!data?.positions || data.positions.length === 0 ? (
              <div className="flex h-32 items-center justify-center rounded-md border border-dashed text-sm text-muted-foreground">
                You have no open paper positions.
              </div>
            ) : (
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>Symbol</TableHead>
                    <TableHead>Strategy</TableHead>
                    <TableHead className="text-right">Qty</TableHead>
                    <TableHead className="text-right">Entry Price</TableHead>
                    <TableHead className="text-right">Mark</TableHead>
                    <TableHead className="text-right">Unrealized P/L</TableHead>
                    <TableHead className="text-right">Actions</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {data.positions.map((pos) => {
                     const pl = (pos.current_mark - pos.avg_entry_price) * pos.quantity * 100
                     // Derive friendly strategy info
                     // strategy_key usually format "SYMBOL_strategytype"
                     const rawKey = pos.strategy_key;
                     let stratPart = rawKey;
                     if (rawKey.includes('_') && rawKey.split('_').length > 1) {
                         // heuristic: "SPY_iron_condor" -> "iron_condor"
                         // But ticker might have underscores? Usually not.
                         const parts = rawKey.split('_');
                         // Assume first part is symbol if it matches pos.symbol
                         if (parts[0] === pos.symbol) {
                            stratPart = parts.slice(1).join('_');
                         }
                     }

                     const meta = getMetadata(stratPart);

                     return (
                    <TableRow key={pos.id}>
                      <TableCell className="font-medium">{pos.symbol}</TableCell>
                      <TableCell>
                        <div className="flex flex-col gap-1">
                           <span className="text-sm font-medium">
                               {meta?.display_name || stratPart}
                           </span>
                           {meta && (
                              <Badge variant="default" className="w-fit text-[10px] px-1.5 py-0 h-5">
                               {meta.risk_profile}
                             </Badge>
                           )}
                           {!meta && stratPart !== rawKey && (
                               <span className="text-xs text-muted-foreground">{rawKey}</span>
                           )}
                        </div>
                      </TableCell>
                      <TableCell className="text-right font-mono">{pos.quantity}</TableCell>
                      <TableCell className="text-right font-mono">${pos.avg_entry_price.toFixed(2)}</TableCell>
                      <TableCell className="text-right font-mono">${pos.current_mark.toFixed(2)}</TableCell>
                      <TableCell className={`text-right font-mono font-bold ${pl >= 0 ? "text-green-500" : "text-red-500"}`}>
                        {pl >= 0 ? "+" : ""}{pl.toFixed(2)}
                      </TableCell>
                      <TableCell className="text-right">
                        <Button variant="ghost" size="sm" onClick={() => handleClosePosition(pos)}>
                          Close
                        </Button>
                      </TableCell>
                    </TableRow>
                  )})}
                </TableBody>
              </Table>
            )}
          </CardContent>
        </Card>

        <ClosePaperPositionModal
          position={selectedPosition}
          open={isCloseModalOpen}
          onClose={() => setIsCloseModalOpen(false)}
          onConfirm={confirmClosePosition}
        />

        <ResetPaperAccountModal
          open={isResetModalOpen}
          onClose={() => setIsResetModalOpen(false)}
          onConfirm={handleResetPortfolio}
          isResetting={isResetting}
        />
      </div>
    </DashboardLayout>
    </RequireAuth>
  )
}
