import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import './style.css';

function App() {
  return (
    <main>
      <p className="eyebrow">Industrial Operations Platform</p>
      <h1>A shared foundation for operational work.</h1>
      <p>Governed workspaces, forms, tasks and approvals for your organization.</p>
      <section aria-labelledby="status-heading">
        <h2 id="status-heading">Platform setup in progress</h2>
        <p>Organization access and My Work will become available as the platform is configured.</p>
      </section>
    </main>
  );
}

const root = document.getElementById('root');
if (!root) throw new Error('Application root is missing');
createRoot(root).render(<StrictMode><App /></StrictMode>);
