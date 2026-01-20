/**
 * PR E: /ops mobile route alias
 *
 * Short URL for mobile access to the Ops Console.
 * Redirects to /admin/ops to avoid import coupling between route segments.
 */
import { redirect } from 'next/navigation';

export default function Page() {
  redirect('/admin/ops');
}
