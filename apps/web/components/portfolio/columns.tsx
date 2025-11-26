"use client"

import { ColumnDef } from "@tanstack/react-table"

// This type is a placeholder. We should eventually replace it with a real type.
export type Position = {
  symbol: string
  quantity: number
  cost_basis: number
  current_price: number
  asset_class: string
}

export const columns: ColumnDef<Position>[] = [
  {
    accessorKey: "symbol",
    header: "Symbol",
  },
  {
    accessorKey: "quantity",
    header: "Quantity",
  },
  {
    accessorKey: "cost_basis",
    header: "Cost Basis",
  },
  {
    accessorKey: "current_price",
    header: "Current Price",
  },
  {
    accessorKey: "asset_class",
    header: "Asset Class",
  },
]
