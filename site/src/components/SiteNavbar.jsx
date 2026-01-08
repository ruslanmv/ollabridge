import React, { useEffect, useMemo, useState } from 'react';
import { Menu, X } from 'lucide-react';

function getPage() {
  const hash = (window.location.hash || '').replace(/^#/, '');
  const pathname = window.location.pathname || '/';
  const raw = hash || pathname;
  const pathPart = raw.split('?')[0] || '/';
  const path = pathPart.startsWith('/') ? pathPart : `/${pathPart}`;
  if (path.startsWith('/docs') || path == '/documentation') return 'docs';
  return 'home';
}

export default function SiteNavbar() {
  const [isOpen, setIsOpen] = useState(false);
  const [page, setPage] = useState(() => getPage());

  useEffect(() => {
    const onChange = () => setPage(getPage());
    window.addEventListener('hashchange', onChange);
    window.addEventListener('popstate', onChange);
    return () => {
      window.removeEventListener('hashchange', onChange);
      window.removeEventListener('popstate', onChange);
    };
  }, []);

  const onHome = page === 'home';

  const navLinkClass = (active) =>
    `px-3 py-2 rounded-md text-sm font-medium transition-colors ${
      active ? 'text-white' : 'text-slate-300 hover:text-white'
    }`;

  const navItem = (href, label, active) => (
    <a href={href} className={navLinkClass(active)} onClick={() => setIsOpen(false)}>
      {label}
    </a>
  );

  return (
    <nav className="fixed w-full z-50 bg-slate-950/80 backdrop-blur-md border-b border-slate-800">
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
        <div className="flex items-center justify-between h-16">
          <a href="#/" className="flex items-center gap-2" onClick={() => setIsOpen(false)}>
            <img
              src="https://raw.githubusercontent.com/ruslanmv/ollabridge/refs/heads/master/assets/logo.svg"
              alt="OllaBridge Logo"
              className="h-8 w-8"
            />
            <span className="text-xl font-bold text-white tracking-tight">
              OllaBridge <span className="text-yellow-400">⚡️</span>
            </span>
          </a>

          <div className="hidden md:block">
            <div className="ml-10 flex items-baseline space-x-8">
              {onHome ? (
                <>
                  <a
                    href="#features"
                    className="text-slate-300 hover:text-white px-3 py-2 rounded-md text-sm font-medium transition-colors"
                  >
                    Features
                  </a>
                  <a
                    href="#architecture"
                    className="text-slate-300 hover:text-white px-3 py-2 rounded-md text-sm font-medium transition-colors"
                  >
                    Architecture
                  </a>
                </>
              ) : (
                <>{navItem('#/', 'Home', false)}</>
              )}

              {navItem('#/docs', 'Documentation', page === 'docs')}
              <a
                href="https://github.com/ruslanmv/ollabridge"
                target="_blank"
                rel="noopener noreferrer"
                className="text-slate-300 hover:text-white px-3 py-2 rounded-md text-sm font-medium transition-colors"
              >
                GitHub
              </a>
            </div>
          </div>

          <div className="hidden md:block">
            <a
              href="#/docs?section=quickstart"
              className="bg-yellow-400 hover:bg-yellow-500 text-slate-900 px-5 py-2 rounded-lg font-bold text-sm transition-all transform hover:scale-105 shadow-[0_0_15px_rgba(250,204,21,0.3)]"
            >
              Get Started
            </a>
          </div>

          <div className="-mr-2 flex md:hidden">
            <button
              onClick={() => setIsOpen(!isOpen)}
              className="inline-flex items-center justify-center p-2 rounded-md text-slate-400 hover:text-white hover:bg-slate-800 focus:outline-none"
            >
              {isOpen ? <X className="h-6 w-6" /> : <Menu className="h-6 w-6" />}
            </button>
          </div>
        </div>
      </div>

      {isOpen && (
        <div className="md:hidden bg-slate-900 border-b border-slate-800">
          <div className="px-2 pt-2 pb-3 space-y-1 sm:px-3">
            {onHome ? (
              <>
                <a
                  href="#features"
                  className="text-slate-300 hover:text-white block px-3 py-2 rounded-md text-base font-medium"
                  onClick={() => setIsOpen(false)}
                >
                  Features
                </a>
                <a
                  href="#architecture"
                  className="text-slate-300 hover:text-white block px-3 py-2 rounded-md text-base font-medium"
                  onClick={() => setIsOpen(false)}
                >
                  Architecture
                </a>
              </>
            ) : (
              <>{navItem('#/', 'Home', false)}</>
            )}

            <a
              href="#/docs"
              className="text-slate-300 hover:text-white block px-3 py-2 rounded-md text-base font-medium"
              onClick={() => setIsOpen(false)}
            >
              Documentation
            </a>

            <a
              href="https://github.com/ruslanmv/ollabridge"
              target="_blank"
              rel="noopener noreferrer"
              className="text-slate-300 hover:text-white block px-3 py-2 rounded-md text-base font-medium"
              onClick={() => setIsOpen(false)}
            >
              GitHub
            </a>

            <a
              href="#/docs?section=quickstart"
              className="mt-2 block text-center bg-yellow-400 hover:bg-yellow-500 text-slate-900 px-4 py-2 rounded-lg font-bold"
              onClick={() => setIsOpen(false)}
            >
              Get Started
            </a>
          </div>
        </div>
      )}
    </nav>
  );
}
