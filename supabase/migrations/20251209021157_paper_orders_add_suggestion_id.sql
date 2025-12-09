ALTER TABLE public.paper_orders
ADD COLUMN IF NOT EXISTS suggestion_id UUID NULL;
