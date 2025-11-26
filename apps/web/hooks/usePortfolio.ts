
import { useState, useEffect } from 'react';
import { supabase } from '@/lib/supabase';
import { API_URL } from '@/lib/constants';

interface FetchOptions extends RequestInit {
  timeout?: number;
}

const fetchWithTimeout = async (resource: RequestInfo, options: FetchOptions = {}) => {
  const { timeout = 8000, ...rest } = options;

  const controller = new AbortController();
  const id = setTimeout(() => controller.abort(), timeout);

  const response = await fetch(resource, {
    ...rest,
    signal: controller.signal,
  });
  clearTimeout(id);
  return response;
};

export const usePortfolio = () => {
  const [positions, setPositions] = useState<any[]>([]);
  const [isLoading, setIsLoading] = useState(true);

  useEffect(() => {
    const loadSnapshot = async () => {
      setIsLoading(true);
      try {
        const { data: { session } } = await supabase.auth.getSession();

        let headers: any = {};
        if (session) {
            headers['Authorization'] = `Bearer ${session.access_token}`;
        }

        const response = await fetchWithTimeout(`${API_URL}/portfolio/snapshot`, {
           headers: headers,
        });

        if (response.ok) {
          const data = await response.json();
          setPositions(data.holdings || []);
        }
      } catch (err) {
        console.error('Failed to load snapshot:', err);
      } finally {
        setIsLoading(false);
      }
    };

    loadSnapshot();
  }, []);

  return { positions, isLoading };
};
