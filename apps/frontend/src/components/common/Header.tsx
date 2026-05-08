import { useState, useRef, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import { useResolvedAppName } from '../../context/AppBrandingContext';
import { useHeaderSession } from '../../context/HeaderSessionContext';

export function Header() {
  const navigate = useNavigate();
  const appName = useResolvedAppName();
  const { user, logout } = useHeaderSession();
  const [showDropdown, setShowDropdown] = useState(false);
  const dropdownRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    function handleClickOutside(event: MouseEvent) {
      if (dropdownRef.current && !dropdownRef.current.contains(event.target as Node)) {
        setShowDropdown(false);
      }
    }
    document.addEventListener('mousedown', handleClickOutside);
    return () => document.removeEventListener('mousedown', handleClickOutside);
  }, []);

  return (
    <header className="oracle-header fixed top-0 left-0 right-0 z-50">
      <div className="flex flex-1 items-center gap-4">
        <svg className="h-5 shrink-0" viewBox="0 0 32 20.4" xmlns="http://www.w3.org/2000/svg" aria-hidden="true">
          <path fill="#C74634" d="M9.9,20.1c-5.5,0-9.9-4.4-9.9-9.9c0-5.5,4.4-9.9,9.9-9.9h11.6c5.5,0,9.9,4.4,9.9,9.9c0,5.5-4.4,9.9-9.9,9.9H9.9 M21.2,16.6c3.6,0,6.4-2.9,6.4-6.4c0-3.6-2.9-6.4-6.4-6.4h-11c-3.6,0-6.4,2.9-6.4,6.4s2.9,6.4,6.4,6.4H21.2"></path>
        </svg>
        <div className="w-px h-8 app-brand-divider--light" />
        <span className="text-xl font-semibold">{appName}</span>
      </div>
      
      {user && (
        <div className="relative" ref={dropdownRef}>
          <button
            onClick={() => setShowDropdown(!showDropdown)}
            className="flex items-center gap-2 px-3 py-2 rounded hover:bg-white hover:bg-opacity-10 transition-colors"
          >
            <span className="text-sm font-medium">
              {user.username}
            </span>
            <svg
              className={`w-4 h-4 transition-transform ${showDropdown ? 'rotate-180' : ''}`}
              fill="none"
              stroke="currentColor"
              viewBox="0 0 24 24"
            >
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7" />
            </svg>
          </button>

          {/* Dropdown Menu */}
          {showDropdown && (
            <div className="absolute right-0 mt-2 w-52 overflow-hidden rounded-xl border border-white/10 bg-[#25211e]/95 py-2 shadow-2xl backdrop-blur-xl">
              <button
                onClick={() => {
                  setShowDropdown(false);
                  navigate('/profile');
                }}
                className="flex w-full items-center gap-2 px-4 py-2.5 text-left text-sm text-white/78 transition-colors hover:bg-white/[0.07] hover:text-white"
              >
                <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M16 7a4 4 0 11-8 0 4 4 0 018 0zM12 14a7 7 0 00-7 7h14a7 7 0 00-7-7z" />
                </svg>
                Edit Profile
              </button>
              <hr className="my-2 border-white/10" />
              <button
                onClick={() => {
                  setShowDropdown(false);
                  logout();
                }}
                className="flex w-full items-center gap-2 px-4 py-2.5 text-left text-sm text-oracle-red transition-colors hover:bg-oracle-red/10 hover:text-[#e45d4c]"
              >
                <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M17 16l4-4m0 0l-4-4m4 4H7m6 4v1a3 3 0 01-3 3H6a3 3 0 01-3-3V7a3 3 0 013-3h4a3 3 0 013 3v1" />
                </svg>
                Sign Out
              </button>
            </div>
          )}
        </div>
      )}
    </header>
  );
}
