import { redirect } from 'next/navigation';

/**
 * The former standalone "Bağlantılar" page is now the "Veri Kaynakları" tab of
 * the unified Integration Center, so a single screen is the front door for
 * connecting everything. This route redirects there to keep old links/bookmarks
 * working.
 */
export default function ConnectionsRedirect() {
  redirect('/integrations?tab=veri-kaynaklari');
}
