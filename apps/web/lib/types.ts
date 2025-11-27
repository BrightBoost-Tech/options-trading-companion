export type Position = {
  id: string;
  symbol: string;
  quantity: number;
  cost_basis: number;
  current_price: number;
  greeks?: {
    delta: number;
    theta: number;
    iv_rank: number;
  };
  risk_warnings?: string[];
  option_contract?: any; // Keep existing fields
  source?: string; // Keep existing fields
};
