/* eslint-disable react-refresh/only-export-components -- context provider and hook intentionally live together to preserve a stable auth API */
/**
 * AuthContext — Frontend authentication state management.
 *
 * Provides login/register/logout + user state to the entire app.
 * Auto-validates stored token on mount.
 */

import {
  createContext,
  useContext,
  useEffect,
  useState,
  useCallback,
  type ReactNode,
} from 'react';
import {
  authApi,
  getStoredToken,
  setStoredToken,
  clearStoredToken,
  type AuthUser,
} from '@/services/auth-api';

// ---- Types ----

type AuthPage = 'login' | 'register' | 'forgot-password' | 'reset-password';

function getInitialAuthPage(): AuthPage {
  const params = new URLSearchParams(window.location.search);
  const requestedPage = params.get('auth');

  if (requestedPage === 'register' || requestedPage === 'forgot-password' || requestedPage === 'reset-password') {
    return requestedPage;
  }

  if (params.get('token') || params.get('reset_token')) {
    return 'reset-password';
  }

  return 'login';
}

function syncAuthPageUrl(page: AuthPage): void {
  const url = new URL(window.location.href);

  if (page === 'login') {
    url.searchParams.delete('auth');
    url.searchParams.delete('token');
    url.searchParams.delete('reset_token');
  } else {
    url.searchParams.set('auth', page);
    if (page !== 'reset-password') {
      url.searchParams.delete('token');
      url.searchParams.delete('reset_token');
    }
  }

  const nextUrl = `${url.pathname}${url.search}${url.hash}`;
  window.history.replaceState({}, '', nextUrl);
}

interface AuthState {
  user: AuthUser | null;
  token: string | null;
  isAuthenticated: boolean;
  isLoading: boolean;
}

interface AuthContextType extends AuthState {
  login: (username: string, password: string) => Promise<void>;
  register: (
    username: string,
    password: string,
    invitationCode: string
  ) => Promise<void>;
  logout: () => void;
  updateUser: (user: AuthUser) => void;
  authPage: AuthPage;
  setAuthPage: (page: AuthPage) => void;
}

// ---- Context ----

const AuthContext = createContext<AuthContextType | null>(null);

export function useAuth(): AuthContextType {
  const context = useContext(AuthContext);
  if (!context) {
    throw new Error('useAuth must be used within AuthProvider');
  }
  return context;
}

// ---- Provider ----

export function AuthProvider({ children }: { children: ReactNode }) {
  const [state, setState] = useState<AuthState>({
    user: null,
    token: getStoredToken(),
    isAuthenticated: false,
    isLoading: true,
  });
  const [authPage, setAuthPageState] = useState<AuthPage>(getInitialAuthPage);

  const setAuthPage = useCallback((page: AuthPage) => {
    setAuthPageState(page);
    syncAuthPageUrl(page);
  }, []);

  // Validate stored token on mount
  useEffect(() => {
    const token = getStoredToken();
    if (token) {
      authApi
        .getMe()
        .then((user) =>
          {
            syncAuthPageUrl('login');
            setState({
              user,
              token,
              isAuthenticated: true,
              isLoading: false,
            });
          }
        )
        .catch(() => {
          clearStoredToken();
          setState({
            user: null,
            token: null,
            isAuthenticated: false,
            isLoading: false,
          });
        });
    } else {
      setState((s) => ({ ...s, isLoading: false }));
    }
  }, []);

  // Listen for global 401 events from API services
  useEffect(() => {
    const handleUnauthorized = () => {
      setState({
        user: null,
        token: null,
        isAuthenticated: false,
        isLoading: false,
      });
      setAuthPage('login');
    };
    window.addEventListener('auth:unauthorized', handleUnauthorized);
    return () => window.removeEventListener('auth:unauthorized', handleUnauthorized);
  }, [setAuthPage]);

  const login = useCallback(
    async (username: string, password: string) => {
      const data = await authApi.login(username, password);
      setStoredToken(data.access_token);
      syncAuthPageUrl('login');
      setState({
        user: data.user,
        token: data.access_token,
        isAuthenticated: true,
        isLoading: false,
      });
    },
    []
  );

  const register = useCallback(
    async (
      username: string,
      password: string,
      invitationCode: string
    ) => {
      await authApi.register(username, password, invitationCode);
      // Let RegisterPage handle success UI + delayed redirect
    },
    []
  );

  const logout = useCallback(() => {
    clearStoredToken();
    setState({
      user: null,
      token: null,
      isAuthenticated: false,
      isLoading: false,
    });
    setAuthPage('login');
  }, [setAuthPage]);

  const updateUser = useCallback((user: AuthUser) => {
    setState((s) => ({ ...s, user }));
  }, []);

  return (
    <AuthContext.Provider
      value={{
        ...state,
        login,
        register,
        logout,
        updateUser,
        authPage,
        setAuthPage,
      }}
    >
      {children}
    </AuthContext.Provider>
  );
}
