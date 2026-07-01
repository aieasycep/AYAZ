import { redirect } from 'next/navigation';

// The budget scenario simulator was merged into the single "Bütçe Aracı" screen
// (/optimizer) as its "Senaryo Simülatörü" tab. Keep this route as a redirect so
// existing links/bookmarks land on the right tab.
export default function BudgetSimulatorRedirect() {
  redirect('/optimizer?tab=senaryo');
}
