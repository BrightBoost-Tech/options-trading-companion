/* Simple env sanity check for dev */
const fs = require("node:fs");
const path = require("node:path");

const REQUIRED = [
  "NEXT_PUBLIC_SUPABASE_URL",
  "SUPABASE_ANON_KEY",
  "SUPABASE_SERVICE_ROLE_KEY"
];

const OPTIONAL = [
  "NEXT_PUBLIC_SUPABASE_ANON_KEY",
  "ANTHROPIC_API_KEY",
  "SNAPTRADE_API_KEY",
  "MARKETDATA_API_KEY",
  "CF_ACCOUNT_ID",
  "CF_API_TOKEN",
  "NEXT_PUBLIC_APP_URL",
  "NODE_ENV"
];

const envFile = path.join(process.cwd(), ".env");
if (!fs.existsSync(envFile)) {
  console.error("❌ .env file not found at project root.");
  console.error("   Create it with:  notepad .env");
  process.exit(1);
}

const content = fs.readFileSync(envFile, "utf8");
const map = new Map();
for (const line of content.split(/\r?\n/)) {
  const m = line.match(/^([^#=\s]+)\s*=\s*(.*)$/);
  if (m) map.set(m[1].trim(), m[2].trim());
}

let ok = true;
console.log("🔎 Checking required environment variables:\n");
for (const key of REQUIRED) {
  const v = map.get(key);
  if (!v || v === "..." || /xxx/i.test(v)) {
    console.log(`❌ ${key} — missing or placeholder`);
    ok = false;
  } else {
    console.log(`✅ ${key}`);
  }
}
console.log("\nℹ️ Optional variables:");
for (const key of OPTIONAL) {
  if (map.has(key)) console.log(`✅ ${key}`);
  else console.log(`⚠️ ${key} — not set (optional)`);
}
if (!ok) {
  console.error("\n❌ Some required variables are missing. Edit .env and run `pnpm env-check` again.");
  process.exit(1);
}
console.log("\n✅ Env check passed.");
