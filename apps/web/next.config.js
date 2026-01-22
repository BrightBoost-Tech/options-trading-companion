/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: false,
  swcMinify: true,
  async rewrites() {
    // Railway: Use BACKEND_URL env var for production, fallback to localhost for local dev
    const backendUrl = (process.env.BACKEND_URL || 'http://127.0.0.1:8000').replace(/\/$/, '');
    return [
      {
        source: '/api/:path*',
        destination: `${backendUrl}/:path*`,
      },
    ]
  },
  async headers() {
    const securityHeaders = [
      {
        key: 'X-DNS-Prefetch-Control',
        value: 'on',
      },
      {
        key: 'X-XSS-Protection',
        value: '1; mode=block',
      },
      {
        key: 'X-Frame-Options',
        value: 'SAMEORIGIN',
      },
      {
        key: 'X-Content-Type-Options',
        value: 'nosniff',
      },
      {
        key: 'Referrer-Policy',
        value: 'strict-origin-when-cross-origin',
      },
      // 🛡️ Sentinel: CSP is omitted for now to avoid breaking inline scripts (theme toggle)
      // and external integrations (Plaid, Supabase) without a rigorous nonce strategy.
      // {
      //   key: 'Content-Security-Policy',
      //   value: "default-src 'self'; script-src 'self' 'unsafe-inline' 'unsafe-eval' ...",
      // }
    ];

    if (process.env.NODE_ENV === 'production') {
      securityHeaders.push({
        key: 'Strict-Transport-Security',
        value: 'max-age=63072000; includeSubDomains; preload',
      });
    }

    return [
      {
        source: '/:path*',
        headers: securityHeaders,
      },
    ];
  },
}

module.exports = nextConfig
