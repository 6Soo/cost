import { useEffect, useLayoutEffect, useRef, useState, type CSSProperties, type ReactNode } from "react";
import { HugeiconsIcon, type IconSvgElement } from "@hugeicons/react";
import {
  ArrowLeftRightIcon,
  Audit01Icon,
  FileSpreadsheetIcon,
  Home01Icon,
  Luggage01Icon,
  MapPinIcon,
  Menu01Icon,
  Moon01Icon,
  MoreHorizontalIcon,
  ReceiptIcon,
  Sun01Icon,
  TransactionIcon,
  UserGroupIcon,
} from "@hugeicons/core-free-icons";
import { cn } from "../lib/cn";

export type AppRole = "owner" | "viewer";
export type AppTrip = { id: string; title: string; href?: string; starts_on?: string; display_key?: string; kind?: "trip" | "quarter"; previous?: boolean; closed?: boolean; archived?: boolean };
export type AppShellProps = {
  role: AppRole;
  trips: AppTrip[];
  path: string;
  children: ReactNode;
  onTripSelect?: (tripId: string) => void;
  className?: string;
  currentTripId?: string;
};
type ThemeMode = "light" | "dark";
type NavItem = { label: string; href: string; match: string[]; icon: IconSvgElement };

const ownerNavigation: NavItem[] = [
  { label: "홈", href: "/", match: ["/"], icon: Home01Icon },
  { label: "여행", href: "/trips", match: ["/trips", "/board", "/participants", "/reserve-links", "/export", "/expense", "/income"], icon: Luggage01Icon },
  { label: "거래", href: "/cards/all", match: ["/cards", "/ota", "/flight-passengers"], icon: TransactionIcon },
  { label: "영수증", href: "/receipts", match: ["/receipts"], icon: ReceiptIcon },
];
const ownerManagement: NavItem[] = [
  { label: "계정·권한", href: "/access/admin", match: ["/access"], icon: UserGroupIcon },
  { label: "Google 장부", href: "/google-ledger", match: ["/google-ledger"], icon: FileSpreadsheetIcon },
  { label: "검수 결과", href: "/review", match: ["/review"], icon: Audit01Icon },
];
const viewerNavigation: NavItem[] = [
  { label: "여행", href: "/trips", match: ["/trips", "/board"], icon: Luggage01Icon },
];

const POPOVER_SELECTOR = "details.cost-trip-switcher, details.cost-bottom-more, .cost-tablet-menu details";

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

function NavIcon({ icon, size = 18, className }: { icon: IconSvgElement; size?: number; className?: string }) {
  return <HugeiconsIcon icon={icon} size={size} strokeWidth={1.8} aria-hidden="true" className={cn("cost-nav-icon", className)} />;
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
      <NavIcon icon={theme === "dark" ? Moon01Icon : Sun01Icon} size={16} />
      <span className="cost-theme-label">{theme === "dark" ? "다크" : "라이트"}</span>
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
                <NavIcon icon={MapPinIcon} size={16} className="cost-trip-icon" />
                <span>{trip.title}</span>
              </button>
            ) : (
              <a className="cost-trip-link" href={href} aria-current={selected ? "page" : undefined}>
                <NavIcon icon={MapPinIcon} size={16} className="cost-trip-icon" />
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
  items: NavItem[];
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
              <NavIcon icon={item.icon} />
              <span>{item.label}</span>
            </a>
          </li>
        );
      })}
    </ul>
  );
}

export function AppShell({ role, trips, path, children, onTripSelect, className, currentTripId = "" }: AppShellProps) {
  const [theme, setTheme] = useState<ThemeMode>(readTheme);
  const shellRef = useRef<HTMLDivElement>(null);
  const currentPath = normalizedPath(path);
  const mainItems = role === "owner" ? ownerNavigation : viewerNavigation;
  const managementItems = role === "owner" ? ownerManagement : [];
  const recentTrips = trips
    .filter((trip) => trip.kind !== "quarter" && !trip.id.startsWith("quarter:"))
    // Match site_shell._active_trip_nav: open trips, current-trip exception,
    // earliest start first, display_key tie-break, missing dates last.
    .filter((trip) => trip.id === currentTripId || !(trip.previous || trip.closed || trip.archived))
    .sort((a, b) => {
      const aDate = a.starts_on || "9999-99-99";
      const bDate = b.starts_on || "9999-99-99";
      if (aDate !== bDate) return aDate < bDate ? -1 : 1;
      const aKey = a.display_key || "";
      const bKey = b.display_key || "";
      return aKey < bKey ? -1 : aKey > bKey ? 1 : 0;
    });

  useLayoutEffect(() => {
    const root = document.documentElement;
    const suppression = document.createElement("style");
    suppression.dataset.costThemeSwap = "";
    suppression.textContent = "*,*::before,*::after{transition:none!important}";
    document.head.append(suppression);
    root.classList.toggle("dark", theme === "dark");
    // Resolve the new theme while transitions are suppressed, including portals.
    void window.getComputedStyle(root).color;
    let restoreFrame = 0;
    const paintFrame = window.requestAnimationFrame(() => {
      restoreFrame = window.requestAnimationFrame(() => suppression.remove());
    });
    try {
      window.localStorage.setItem("cost-theme", theme);
    } catch {
      // Theme changes still work for this tab when browser storage is unavailable.
    }
    return () => {
      window.cancelAnimationFrame(paintFrame);
      window.cancelAnimationFrame(restoreFrame);
      suppression.remove();
    };
  }, [theme]);

  // Shell popovers (trip switcher, tablet menu, bottom "more") are native <details>:
  // they do not dismiss on Escape or outside pointer by themselves. Close them here
  // without touching the modal drawer, which handles its own Escape and focus restore.
  useEffect(() => {
    const shell = shellRef.current;
    if (!shell) return;
    const popovers = () => Array.from(shell.querySelectorAll<HTMLDetailsElement>(POPOVER_SELECTOR));
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key !== "Escape") return;
      const open = popovers().filter((details) => details.open);
      if (open.length === 0) return;
      event.stopPropagation();
      for (const details of open) details.open = false;
      open[0].querySelector("summary")?.focus();
    };
    const onPointerDown = (event: PointerEvent) => {
      const target = event.target;
      if (!(target instanceof Node)) return;
      for (const details of popovers()) {
        if (details.open && !details.contains(target)) details.open = false;
      }
    };
    document.addEventListener("keydown", onKeyDown, true);
    document.addEventListener("pointerdown", onPointerDown, true);
    return () => {
      document.removeEventListener("keydown", onKeyDown, true);
      document.removeEventListener("pointerdown", onPointerDown, true);
    };
  }, []);

  // Selecting a trip or navigating from a popover closes it once the route changes.
  useEffect(() => {
    const shell = shellRef.current;
    if (!shell) return;
    for (const details of Array.from(shell.querySelectorAll<HTMLDetailsElement>(POPOVER_SELECTOR))) {
      details.open = false;
    }
  }, [path]);

  // Acceptance #6: each screen needs a unique page <title>. Follow the visible
  // screen heading rather than the route alone, because the ledger h1 only settles
  // after its async load; observe the main subtree so the title tracks that change.
  useEffect(() => {
    const main = document.getElementById("cost-main");
    if (!main) return;
    const syncTitle = () => {
      const label = main.querySelector("h1")?.textContent?.trim();
      const next = label ? `${label} · COST` : "COST";
      if (document.title !== next) document.title = next;
    };
    syncTitle();
    const observer = new MutationObserver(syncTitle);
    observer.observe(main, { childList: true, subtree: true, characterData: true });
    return () => observer.disconnect();
  }, []);

  const toggleTheme = () => setTheme((previous) => previous === "dark" ? "light" : "dark");

  return (
    <div className={cn("cost-app-shell", className)} data-role={role} ref={shellRef}>
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
                <p className="cost-sidebar-heading">진행 중 여행</p>
                <TripLinks trips={recentTrips} onTripSelect={onTripSelect} currentPath={path} />
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
                  <summary aria-label="여행 전환">
                    <NavIcon icon={ArrowLeftRightIcon} />
                    <span className="cost-topbar-label">여행 전환</span>
                  </summary>
                  <div className="cost-trip-switcher-panel">
                    <TripLinks trips={trips} onTripSelect={onTripSelect} currentPath={path} />
                  </div>
                </details>
              )}
              <div className="cost-tablet-menu">
                <details>
                  <summary className="cost-menu-trigger" aria-label="메뉴">
                    <NavIcon icon={Menu01Icon} />
                    <span className="cost-topbar-label">메뉴</span>
                  </summary>
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
            {mainItems.map((item) => (
              <a key={item.href} className="cost-bottom-link" href={item.href} aria-current={isActive(currentPath, item.match) ? "page" : undefined}>
                <NavIcon icon={item.icon} size={20} />
                <span>{item.label}</span>
              </a>
            ))}
            {role === "owner" && (
              <details className="cost-bottom-more">
                <summary className="cost-bottom-link" aria-label="더보기">
                  <NavIcon icon={MoreHorizontalIcon} size={20} />
                  <span>더보기</span>
                </summary>
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
