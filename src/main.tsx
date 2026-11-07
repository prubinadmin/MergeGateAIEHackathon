import { useEffect, useState, type ReactNode } from 'react';
import { createRoot } from 'react-dom/client';
import { Lock, Radio, Wrench } from 'lucide-react';
import App from './App.tsx';
import WarRoom from './warroom/WarRoom.tsx';
import './index.css';

type View = 'simulator' | 'live';

// The live gate is the landing page: it is the real system (or a labelled recording of it).
// The simulator shows simulated data, so it is only reachable on purpose via #simulator.
const fromHash = (): View => (location.hash === '#simulator' ? 'simulator' : 'live');

function Root() {
  const [view, setView] = useState<View>(fromHash);
  useEffect(() => {
    const onHash = () => setView(fromHash());
    window.addEventListener('hashchange', onHash);
    return () => window.removeEventListener('hashchange', onHash);
  }, []);
  const go = (v: View) => {
    setView(v);
    history.replaceState(null, '', v === 'simulator' ? '#simulator' : location.pathname + location.search);
  };
  const tab = (v: View, label: string, icon: ReactNode) => (
    <button
      onClick={() => go(v)}
      aria-current={view === v ? 'page' : undefined}
      className={`flex items-center gap-1.5 rounded-lg px-3 py-1.5 text-[13px] transition-colors duration-150 focus-visible:outline focus-visible:outline-2 focus-visible:outline-amber-400 ${view === v ? 'bg-zinc-800 text-zinc-100' : 'text-zinc-400 hover:text-zinc-200'}`}>
      {icon}{label}
    </button>
  );
  // Both views stay mounted so a live gate run survives a tab switch; each view owns its background.
  return (
    <div className="flex min-h-screen flex-col selection:bg-amber-500/30">
      <nav className="flex items-center gap-6 border-b border-zinc-900 bg-[#0a0a0b] px-6 py-2">
        <span className="flex items-center gap-2 text-[15px] font-semibold text-zinc-100">
          <span className="flex h-7 w-7 items-center justify-center rounded-full border border-amber-500/70 text-amber-400"><Lock size={14} /></span>
          Merge Gate
        </span>
        <div className="flex items-center gap-1">
          {tab('live', 'Live gate', <Radio size={14} />)}
          {tab('simulator', 'Simulator (simulated data)', <Wrench size={14} />)}
        </div>
        <span className="ml-auto hidden text-[12px] text-zinc-500 md:block">The right engineer, on their phone, with proof.</span>
      </nav>
      <div className={view === 'simulator' ? 'flex flex-1 flex-col' : 'hidden'}><App /></div>
      <div className={view === 'live' ? 'flex flex-1 flex-col' : 'hidden'}><WarRoom /></div>
    </div>
  );
}

createRoot(document.getElementById('root')!).render(<Root />);
