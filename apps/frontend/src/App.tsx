import { BrowserRouter } from 'react-router-dom';

import { SessionScopedApp } from './app/SessionScopedApp';
import { AuthProvider } from './context/AuthContext';
import { ToastProvider } from './context/ToastContext';
import './styles/oracle-theme.css';

function App() {
  return (
    <BrowserRouter
      future={{
        v7_startTransition: true,
        v7_relativeSplatPath: true,
      }}
    >
      <AuthProvider>
        <ToastProvider>
          <SessionScopedApp />
        </ToastProvider>
      </AuthProvider>
    </BrowserRouter>
  );
}

export default App;
