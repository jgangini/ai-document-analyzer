import type { ReactNode } from 'react';
import { useState } from 'react';

import { Header } from './Header';
import { Sidebar } from './Sidebar';
import { Footer } from './Footer';

interface LayoutProps {
  children: ReactNode;
  contentContainerClassName?: string;
  mainMarginBottom?: string;
}

export function Layout({ children, contentContainerClassName, mainMarginBottom = '34px' }: LayoutProps) {
  const [sidebarCollapsed, setSidebarCollapsed] = useState(
    () => sessionStorage.getItem('sidebarCollapsed') === 'true'
  );

  const handleSidebarToggle = () => {
    setSidebarCollapsed((prev) => {
      const next = !prev;
      sessionStorage.setItem('sidebarCollapsed', next ? 'true' : 'false');
      return next;
    });
  };

  return (
    <div className="app-shell-dark min-h-screen flex flex-col">
      <Header />
      <div className="app-content-layer flex flex-1 pt-14">
        <Sidebar collapsed={sidebarCollapsed} onToggle={handleSidebarToggle} />
        <main
          className={`flex-1 transition-all duration-300 ${
            sidebarCollapsed ? 'ml-16' : 'ml-52'
          }`}
          style={{ marginBottom: mainMarginBottom }}
        >
          <div className={contentContainerClassName ?? 'max-w-7xl mx-auto px-6 py-8'}>{children}</div>
        </main>
      </div>
      <Footer />
    </div>
  );
}
