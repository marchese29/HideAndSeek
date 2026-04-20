/**
 * Read a required env var, throwing a clear error if missing or empty.
 *
 * Used for values the repo refuses to hardcode (domain names, hosted zone
 * names) — operator-supplied via infra/cdk/.env, documented in .env.example.
 */
export function requireEnv(name: string): string {
  const value = process.env[name];
  if (value === undefined || value === '') {
    throw new Error(
      `Missing required env var ${name}. Load infra/cdk/.env: ` +
        `set -a; source infra/cdk/.env; set +a`,
    );
  }
  return value;
}
