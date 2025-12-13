## 2024-05-23 - Table Accessibility
**Learning:** Tables in the dashboard were missing `scope="col"` attributes on header cells, making column associations ambiguous for screen reader users.
**Action:** Always verify `th` elements have appropriate `scope` attributes (`col` or `row`) during component creation.
## 2024-05-23 - Build Environment Fixes\n**Learning:** The frontend build environment was missing critical CSS utility definitions and environment variables, causing 'border-border' syntax errors and Supabase client initialization failures.\n**Action:** When working on the frontend, always verify that `globals.css` defines standard utility classes if a full Tailwind config is absent, and ensure `.env.local` exists for static generation.
