import { useState, type ReactNode } from 'react';
import { createRoot } from 'react-dom/client';
import { Lock, Radio, Wrench } from 'lucide-react';
import App from './App.tsx';
import WarRoom from './warroom/WarRoom.tsx';
import './index.css';

type View = 'live' | 'simulator';

function Root() {
  const [view, setView] = useState<View>(() => (location.hash === '#simulator' ? 'simulator' : 'live'));
  const go = (v: View) => {
    setView(v);
    history.replaceState(null, '', v === 'simulator' ? '#simulator' : '#');
  };
  const tab = (v: View, label: string, icon: ReactNode) => (
    <button
      onClick={() => go(v)}
      aria-current={view === v ? 'page' : undefined}
      className={`flex items-center gap-1.5 rounded-lg px-3 py-1.5 text-[13px] transition-colors duration-150 focus-visible:outline focus-visible:outline-2 focus-visible:outline-amber-400 ${view === v ? 'bg-zinc-800 text-zinc-100' : 'text-zinc-400 hover:text-zinc-200'}`}>
      {icon}{label}
    </button>
  );
  return (
    <div className="min-h-screen bg-[#0a0a0b] selection:bg-amber-500/30">
      <nav className="flex items-center gap-6 border-b border-zinc-900 px-6 py-3">
        <span className="flex items-center gap-2 text-[15px] font-semibold text-zinc-100">
          <span className="flex h-7 w-7 items-center justify-center rounded-full border border-amber-500/70 text-amber-400"><Lock size={14} /></span>
          Merge Gate
        </span>
        <div className="flex items-center gap-1">
          {tab('live', 'Live gate', <Radio size={14} />)}
          {tab('simulator', 'Simulator', <Wrench size={14} />)}
        </div>
        <span className="ml-auto hidden text-[12px] text-zinc-500 md:block">The right engineer, on their phone, with proof.</span>
      </nav>
      {view === 'live' ? <WarRoom /> : <App />}
    </div>
  );
}

createRoot(document.getElementById('root')!).render(<Root />);
