import { lazy, Suspense } from 'react';
import { Navigate, Route } from 'react-router-dom';

import { LoadingState } from '../components/common/LoadingState';

const LoginForm = lazy(() =>
  import('../components/auth/LoginForm').then((module) => ({ default: module.LoginForm }))
);
const Chat = lazy(() => import('../components/pages/Chat').then((module) => ({ default: module.Chat })));
const ContinuousImprovement = lazy(() =>
  import('../components/pages/ContinuousImprovement').then((module) => ({
    default: module.ContinuousImprovement,
  }))
);
const Home = lazy(() => import('../components/pages/Home').then((module) => ({ default: module.Home })));
const Metadata = lazy(() =>
  import('../components/pages/Metadata').then((module) => ({ default: module.Metadata }))
);
const Profile = lazy(() =>
  import('../components/pages/Profile').then((module) => ({ default: module.Profile }))
);
const RAG = lazy(() => import('../components/pages/RAG').then((module) => ({ default: module.RAG })));
const Settings = lazy(() =>
  import('../components/pages/Settings').then((module) => ({ default: module.Settings }))
);
const Users = lazy(() => import('../components/pages/Users').then((module) => ({ default: module.Users })));

type AuthenticatedRoutesProps = {
  isAuthenticated: boolean;
};

function protectedElement(isAuthenticated: boolean, element: JSX.Element): JSX.Element {
  return isAuthenticated ? element : <Navigate to="/login" replace />;
}

function routeElement(element: JSX.Element): JSX.Element {
  return (
    <Suspense fallback={<LoadingState size="sm" label="Loading..." />}>
      {element}
    </Suspense>
  );
}

export function AuthenticatedRoutes({ isAuthenticated }: AuthenticatedRoutesProps) {
  return (
    <>
      <Route path="/login" element={routeElement(<LoginForm />)} />
      <Route path="/home" element={protectedElement(isAuthenticated, routeElement(<Home />))} />
      <Route path="/chat" element={protectedElement(isAuthenticated, routeElement(<Chat />))} />
      <Route path="/rag" element={protectedElement(isAuthenticated, routeElement(<RAG />))} />
      <Route
        path="/observability"
        element={protectedElement(isAuthenticated, routeElement(<ContinuousImprovement />))}
      />
      <Route path="/improvement" element={<Navigate to="/observability" replace />} />
      <Route path="/metadata" element={protectedElement(isAuthenticated, routeElement(<Metadata />))} />
      <Route path="/profile" element={protectedElement(isAuthenticated, routeElement(<Profile />))} />
      <Route path="/users" element={protectedElement(isAuthenticated, routeElement(<Users />))} />
      <Route path="/settings" element={protectedElement(isAuthenticated, routeElement(<Settings />))} />
      <Route path="*" element={<Navigate to={isAuthenticated ? '/home' : '/login'} replace />} />
    </>
  );
}
