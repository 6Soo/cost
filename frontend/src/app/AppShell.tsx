import { useLayoutEffect, useState, type CSSProperties, type ReactNode } from "react";
import { cn } from "../lib/cn";

export type AppRole = "owner" | "viewer";
export type AppTrip = { id: string; title: string; href?: string };
export type AppShellProps = {
  role: AppRole;
  trips: AppTrip[];
  path: string;
  children: ReactNode;
  onTripSelect?: (tripId: string) => void;
  className?: string;
};
type ThemeMode = "light" | "dark";

const ownerNavigation = [
  { label: "홈", href: "/", match: ["/"] },
  { label: "여행", href: "/trips", match: ["/trips", "/board", "/participants", "/reserve-links", "/export", "/expense", "/income"] },
  { label: "거래", href: "/cards/all", match: ["/cards", "/ota", "/flight-passengers"] },
  { label: "영수증", href: "/receipts", match: ["/receipts"] },
];
const ownerManagement = [
  { label: "계정·권한", href: "/access/admin", match: ["/access"] },
  { label: "Google 장부", href: "/google-ledger", match: ["/google-ledger"] },
  { label: "검수 결과", href: "/review", match: ["/review"] },
];

function normalizedPath(path: string): string {
  const withoutPrefix = path.replace(/^\/ui(?=\/|$)/, "");
  return withoutPrefix || "/";
}

function isActive(path: string, matches: string[]): boolean {
  return matches.some((match) => path === match || (match !== "/" && path.startsWith(`${match}/`)));
}

function titleForPath(path: string): string {
  const allItems = [...ownerNavigation, ...ownerManagement];
  return allItems.find((item) => isActive(path, item.match))?.label ?? (path === "/" ? "홈" : "COST");
}

function readTheme(): ThemeMode {
  try {
    return window.localStorage.getItem("cost-theme") === "dark" ? "dark" : "light";
  } catch {
    return "light";
  }
}

function themeButtonLabel(theme: ThemeMode): string {
  return theme === "dark" ? "라이트 모드로 전환" : "다크 모드로 전환";
}

function ThemeToggle({ theme, onToggle }: { theme: ThemeMode; onToggle: () => void }) {
  return (
    <button
      type="button"
      className="cost-theme-toggle"
      aria-label={themeButtonLabel(theme)}
      aria-pressed={theme === "dark"}
      onClick={onToggle}
    >
      <span aria-hidden="true" className="cost-theme-dot" />
      <span>{theme === "dark" ? "다크" : "라이트"}</span>
    </button>
  );
}

function TripLinks({ trips, onTripSelect, currentPath, className }: {
  trips: AppTrip[];
  onTripSelect?: (tripId: string) => void;
  currentPath: string;
  className?: string;
}) {
  if (trips.length === 0) return null;
  return (
    <ul className={cn("cost-trip-links", className)}>
      {trips.slice(0, 8).map((trip) => {
        const href = trip.href ?? `/board?tab=${encodeURIComponent(trip.id)}`;
        const selected = currentPath.includes(encodeURIComponent(trip.id));
        return (
          <li key={trip.id}>
            {onTripSelect && !trip.href ? (
              <button type="button" className="cost-trip-link" aria-current={selected ? "page" : undefined} onClick={() => onTripSelect(trip.id)}>
                <span className="cost-trip-mark" aria-hidden="true" />
                <span>{trip.title}</span>
              </button>
            ) : (
              <a className="cost-trip-link" href={href} aria-current={selected ? "page" : undefined}>
                <span className="cost-trip-mark" aria-hidden="true" />
                <span>{trip.title}</span>
              </a>
            )}
          </li>
        );
      })}
    </ul>
  );
}

function NavigationLinks({ items, path, className }: {
  items: typeof ownerNavigation;
  path: string;
  className?: string;
}) {
  return (
    <ul className={cn("cost-nav-list", className)}>
      {items.map((item) => {
        const current = isActive(path, item.match);
        return (
          <li key={item.href}>
            <a className="cost-nav-link" href={item.href} aria-current={current ? "page" : undefined}>
              <span className="cost-nav-mark" aria-hidden="true" />
              <span>{item.label}</span>
            </a>
          </li>
        );
      })}
    </ul>
  );
}

export function AppShell({ role, trips, path, children, onTripSelect, className }: AppShellProps) {
  const [theme, setTheme] = useState<ThemeMode>(readTheme);
  const currentPath = normalizedPath(path);
  const mainItems = role === "owner" ? ownerNavigation : [{ label: "여행", href: "/trips", match: ["/trips", "/board"] }];
  const managementItems = role === "owner" ? ownerManagement : [];

  useLayoutEffect(() => {
    const root = document.documentElement;
    root.classList.toggle("dark", theme === "dark");
    try {
      window.localStorage.setItem("cost-theme", theme);
    } catch {
      // Theme changes still work for this tab when browser storage is unavailable.
    }
  }, [theme]);

  const toggleTheme = () => setTheme((previous) => previous === "dark" ? "light" : "dark");

  return (
    <div className={cn("cost-app-shell", className)} data-role={role}>
      <a className="cost-skip-link" href="#cost-main">본문으로 건너뛰기</a>
      <div className="cost-workspace">
        <aside className="cost-sidebar" aria-label="기본 탐색">
          <a className="cost-brand" href="/" aria-label="COST 홈">
            <span className="cost-brand-mark" aria-hidden="true">C</span>
            <span className="cost-brand-name">COST</span>
          </a>
          {role === "owner" ? (
            <>
              <NavigationLinks items={ownerNavigation} path={currentPath} />
              <div className="cost-sidebar-section">
                <p className="cost-sidebar-heading">최근 여행</p>
                <TripLinks trips={trips} onTripSelect={onTripSelect} currentPath={path} />
              </div>
            </>
          ) : (
            <div className="cost-sidebar-section">
              <p className="cost-sidebar-heading">허용된 여행</p>
              <TripLinks trips={trips} onTripSelect={onTripSelect} currentPath={path} />
            </div>
          )}
          <div className="cost-sidebar-footer">
            {managementItems.length > 0 && <NavigationLinks items={managementItems} path={currentPath} />}
            <ThemeToggle theme={theme} onToggle={toggleTheme} />
            <span className="cost-role-label">{role === "owner" ? "관리 권한" : "조회 권한"}</span>
          </div>
        </aside>

        <div className="cost-content">
          <header className="cost-topbar">
            <div className="cost-topbar-location" aria-label="현재 위치">COST <span aria-hidden="true">/</span> {titleForPath(currentPath)}</div>
            <div className="cost-topbar-actions">
              {trips.length > 0 && (
                <details className="cost-trip-switcher">
                  <summary aria-label="여행 전환">여행 전환</summary>
                  <div className="cost-trip-switcher-panel">
                    <TripLinks trips={trips} onTripSelect={onTripSelect} currentPath={path} />
                  </div>
                </details>
              )}
              <div className="cost-tablet-menu">
                <details>
                  <summary className="cost-menu-trigger">메뉴</summary>
                  <div className="cost-tablet-menu-panel">
                    <NavigationLinks items={mainItems} path={currentPath} />
                    {managementItems.length > 0 && <NavigationLinks items={managementItems} path={currentPath} />}
                    {role === "viewer" && <TripLinks trips={trips} onTripSelect={onTripSelect} currentPath={path} />}
                  </div>
                </details>
              </div>
              <div className="cost-mobile-theme"><ThemeToggle theme={theme} onToggle={toggleTheme} /></div>
            </div>
          </header>

          <div className="cost-main" id="cost-main" tabIndex={-1}>{children}</div>

          <nav className="cost-bottom-nav" aria-label="주요 탐색" style={{ "--cost-nav-count": role === "owner" ? 5 : 1 } as CSSProperties}>
            {(role === "owner" ? ownerNavigation : [{ label: "여행", href: "/trips", match: ["/trips", "/board"] }]).map((item) => (
              <a key={item.href} className="cost-bottom-link" href={item.href} aria-current={isActive(currentPath, item.match) ? "page" : undefined}>
                <span className="cost-nav-mark" aria-hidden="true" />
                <span>{item.label}</span>
              </a>
            ))}
            {role === "owner" && (
              <details className="cost-bottom-more">
                <summary className="cost-bottom-link">더보기</summary>
                <div className="cost-bottom-more-panel">
                  <NavigationLinks items={ownerManagement} path={currentPath} />
                  <ThemeToggle theme={theme} onToggle={toggleTheme} />
                </div>
              </details>
            )}
          </nav>
        </div>
      </div>
    </div>
  );
}
