import Link from 'next/link';
import { buttonVariants } from '@/components/ui/button';

export default function Home() {
  return (
    <main className="flex min-h-screen flex-col items-center justify-center p-24">
      <div className="max-w-2xl text-center">
        <h1 className="text-5xl font-bold mb-6">Options Trading Companion</h1>
        <p className="text-xl text-gray-600 mb-8">
          AI-powered trade scouting with automated guardrail learning
        </p>
        <div className="flex gap-4 justify-center">
          <Link
            href="/login"
            className={buttonVariants({ size: 'lg' })}
          >
            Login
          </Link>
          <Link
            href="/signup"
            className={buttonVariants({ variant: 'outline', size: 'lg' })}
          >
            Sign Up
          </Link>
        </div>
      </div>
    </main>
  );
}
