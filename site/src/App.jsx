import React, { useEffect, useState } from 'react';
import Home from './pages/Home.jsx';
import Documentation from './pages/Documentation.jsx';

function parseRoute() {
  const hash = (window.location.hash || '').replace(/^#/, '');
  const pathname = window.location.pathname || '/';

  // Prefer hash navigation (works on static hosting without server rewrites).
  const raw = hash || pathname;

  const parts = raw.split('?');
  const pathPart = parts[0] || '/';
  const queryPart = parts[1] || '';

  let path = pathPart.startsWith('/') ? pathPart : `/${pathPart}`;
  if (path === '/documentation') path = '/docs';

  const params = new URLSearchParams(queryPart);
  const section = params.get('section') || params.get('s') || '';

  const page = path.startsWith('/docs') ? 'docs' : 'home';
  return { page, section };
}

export default function App() {
  const [route, setRoute] = useState(() => parseRoute());

  useEffect(() => {
    const onChange = () => setRoute(parseRoute());
    window.addEventListener('hashchange', onChange);
    window.addEventListener('popstate', onChange);
    return () => {
      window.removeEventListener('hashchange', onChange);
      window.removeEventListener('popstate', onChange);
    };
  }, []);

  if (route.page === 'docs') {
    return <Documentation initialSection={route.section} />;
  }

  return <Home />;
}
