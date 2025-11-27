import { createClientComponentClient } from "@supabase/auth-helpers-nextjs";

export async function fetchWithAuth(endpoint: string, options: any = {}) {
  const supabase = createClientComponentClient();
  const { data } = await supabase.auth.getSession();

  if (!data.session?.access_token) {
    throw new Error("No active session");
  }

  const res = await fetch(`${process.env.NEXT_PUBLIC_API_URL}${endpoint}`, {
    ...options,
    headers: {
      ...options.headers,
      "Authorization": `Bearer ${data.session.access_token}`, // CRITICAL
      "Content-Type": "application/json",
    },
  });

  if (res.status === 401) {
    // Optional: redirect to login or trigger a reauth flow
    window.location.href = "/login";
  }

  return res.json();
}
