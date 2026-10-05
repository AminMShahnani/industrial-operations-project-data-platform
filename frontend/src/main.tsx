import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import { AuthProvider } from 'react-oidc-context';
import { authSettings } from './auth';
import { Administration } from './Admin';
import './style.css';

function App() {
  let settings;
  try {
    settings = authSettings(import.meta.env.VITE_OIDC_AUTHORITY, import.meta.env.VITE_OIDC_CLIENT_ID,
      window.location.origin + '/', window.sessionStorage, import.meta.env.PROD);
  } catch {
    return <main><h1>Industrial Operations Platform</h1><p role="alert">Organization sign-in is unavailable. Contact your administrator.</p></main>;
  }
  return (
    <main>
      <p className="eyebrow">Industrial Operations Platform</p>
      <h1>A shared foundation for operational work.</h1>
      <p>Governed workspaces, forms, tasks and approvals for your organization.</p>
      {settings ? <AuthProvider {...settings} onSigninCallback={() => window.history.replaceState({}, '', '/')}>
        <Administration />
      </AuthProvider> : <section aria-labelledby="status-heading">
        <h2 id="status-heading">Platform setup in progress</h2>
        <p>Organization access and My Work will become available as the platform is configured.</p>
      </section>}
    </main>
  );
}

const root = document.getElementById('root');
if (!root) throw new Error('Application root is missing');
createRoot(root).render(<StrictMode><App /></StrictMode>);
