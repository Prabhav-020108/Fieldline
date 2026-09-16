"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { LogIn } from "lucide-react";

import { Button, Card, Field, Input } from "@/components/ui";
import { login } from "@/lib/api";

export default function LoginPage() {
  const router = useRouter();
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setLoading(true);
    setError(null);
    try {
      const { access_token } = await login(username, password);
      localStorage.setItem("fieldline_token", access_token);
      router.push("/");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not log in.");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="min-h-screen flex items-center justify-center bg-[var(--paper)] px-4">
      <div className="w-full max-w-sm">
        <div className="flex items-center gap-2.5 justify-center mb-6">
          <span className="flex h-9 w-9 items-center justify-center rounded-[var(--radius-sm)] bg-[var(--brand)] text-white">
            <LogIn size={16} />
          </span>
          <span className="text-lg font-semibold tracking-tight text-[var(--ink)]">
            FieldLine
          </span>
        </div>
        <Card>
          <h1 className="text-base font-semibold text-[var(--ink)] mb-1">Sign in</h1>
          <p className="text-sm text-[var(--ink-muted)] mb-5">
            Use an account provisioned by your admin. Demo accounts (see{" "}
            <code className="font-mono text-xs">backend/seed_db.py</code>):
            e.g. <code className="font-mono text-xs">dispatcher.demo</code> /{" "}
            <code className="font-mono text-xs">FieldLine123!</code>.
          </p>
          <form onSubmit={handleSubmit} className="space-y-4">
            <Field label="Username">
              <Input
                autoFocus
                value={username}
                onChange={(e) => setUsername(e.target.value)}
                placeholder="dispatcher.demo"
                required
              />
            </Field>
            <Field label="Password">
              <Input
                type="password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                placeholder="••••••••"
                required
              />
            </Field>
            {error ? <p className="text-sm text-[var(--danger)]">{error}</p> : null}
            <Button type="submit" disabled={loading} className="w-full justify-center">
              {loading ? "Signing in..." : "Sign in"}
            </Button>
          </form>
        </Card>
      </div>
    </div>
  );
}