import { useState } from 'react';
import { createRoot } from 'react-dom/client';
import { Lock, Radio, Wrench } from 'lucide-react';
import App from './App.tsx';
import WarRoom from './warroom/WarRoom.tsx';
import './index.css';

type View = 'warroom' | 'simulator';

function Root() {
  const [view, setView] = useState<View>(() => (location.hash === '#simulator' ? 'simulator' : 'warroom'));
  const go = (v: View) => {
    setView(v);
    history.replaceState(null, '', v === 'simulator' ? '#simulator' : '#');
  };
  const tab = (v: View, label: string, icon: React.ReactNode) => (
    <button onClick={() => go(v)}
      className={`flex items-center gap-1.5 rounded-lg px-3 py-1.5 text-[13px] transition ${view === v ? 'bg-zinc-800 text-zinc-100' : 'text-zinc-400 hover:text-zinc-200'}`}>
      {icon}{label}
    </button>
  );
  return (
    <div className="min-h-screen bg-[#0a0a0b]">
      <nav className="flex items-center gap-6 border-b border-zinc-900 px-6 py-3">
        <span className="flex items-center gap-2 text-[15px] font-semibold text-zinc-100">
          <span className="flex h-7 w-7 items-center justify-center rounded-full border border-amber-500/70 text-amber-400"><Lock size={14} /></span>
          Merge Gate
        </span>
        <div className="flex items-center gap-1">
          {tab('warroom', 'War Room', <Radio size={14} />)}
          {tab('simulator', 'Concept simulator', <Wrench size={14} />)}
        </div>
        <span className="ml-auto text-[12px] text-zinc-500">The right engineer, on their phone, with proof.</span>
      </nav>
      {view === 'warroom' ? <WarRoom /> : <App />}
    </div>
  );
}

createRoot(document.getElementById('root')!).render(<Root />);
