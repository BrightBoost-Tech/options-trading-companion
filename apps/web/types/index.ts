export interface Holding {
  id?: string; 
  symbol: string;
  name?: string;
  quantity: number;
  cost_basis?: number;
  current_price: number;
  currency: string;
  institution_name?: string;
};

export interface SyncResponse {
  status: string;
  count: number;
  holdings: Holding[];
}
