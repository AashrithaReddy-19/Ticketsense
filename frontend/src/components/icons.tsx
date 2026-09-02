import type { SVGProps } from "react";

/** Minimal hand-authored line-icon set (24x24, stroke-based) so the app doesn't need to
 * bundle an icon library for ~30 glyphs. All icons share the same visual weight. */
type IconProps = SVGProps<SVGSVGElement> & { size?: number };

function base(paths: React.ReactNode) {
  return function IconComponent({ size = 18, ...props }: IconProps) {
    return (
      <svg
        width={size}
        height={size}
        viewBox="0 0 24 24"
        fill="none"
        stroke="currentColor"
        strokeWidth={1.8}
        strokeLinecap="round"
        strokeLinejoin="round"
        aria-hidden="true"
        focusable="false"
        {...props}
      >
        {paths}
      </svg>
    );
  };
}

export const IconDashboard = base(<><rect x="3" y="3" width="7" height="9" rx="1.5" /><rect x="14" y="3" width="7" height="5" rx="1.5" /><rect x="14" y="12" width="7" height="9" rx="1.5" /><rect x="3" y="16" width="7" height="5" rx="1.5" /></>);
export const IconTickets = base(<><path d="M3 8a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2v2a2 2 0 0 0 0 4v2a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-2a2 2 0 0 0 0-4z" /><path d="M10 8v8" strokeDasharray="2 3" /></>);
export const IconQueue = base(<><path d="M4 6h16M4 12h16M4 18h10" /></>);
export const IconKnowledge = base(<><path d="M4 5.5A2.5 2.5 0 0 1 6.5 3H20v15.5A2.5 2.5 0 0 0 17.5 21H6.5A2.5 2.5 0 0 1 4 18.5z" /><path d="M4 18.5A2.5 2.5 0 0 1 6.5 16H20" /></>);
export const IconBell = base(<><path d="M6 9a6 6 0 1 1 12 0c0 5 2 6 2 6H4s2-1 2-6" /><path d="M9.5 19a2.5 2.5 0 0 0 5 0" /></>);
export const IconAlert = base(<><path d="M12 3 2 20h20z" /><path d="M12 10v4" /><circle cx="12" cy="17" r="0.6" fill="currentColor" stroke="none" /></>);
export const IconSparkle = base(<><path d="M12 3v3M12 18v3M3 12h3M18 12h3" /><path d="M12 7.5 13.4 11l3.6 1.4-3.6 1.4L12 17.2l-1.4-3.4L7 12.4l3.6-1.4z" /></>);
export const IconChart = base(<><path d="M4 20V10M11 20V4M18 20v-7" /><path d="M2 20h20" /></>);
export const IconSettings = base(<><circle cx="12" cy="12" r="3" /><path d="M19.4 13a7.9 7.9 0 0 0 .1-2l2-1.4-2-3.4-2.3.7a8 8 0 0 0-1.7-1L15 3h-6l-.5 2.9a8 8 0 0 0-1.7 1l-2.3-.7-2 3.4L4.5 11a8 8 0 0 0 0 2l-2 1.4 2 3.4 2.3-.7c.5.4 1.1.8 1.7 1L9 21h6l.5-2.9c.6-.2 1.2-.6 1.7-1l2.3.7 2-3.4z" /></>);
export const IconShield = base(<><path d="M12 3 5 6v6c0 4.4 3 7.7 7 9 4-1.3 7-4.6 7-9V6z" /><path d="m9.5 12 1.8 1.8L15 10" /></>);
export const IconPlug = base(<><path d="M9 3v5M15 3v5" /><rect x="6" y="8" width="12" height="6" rx="2" /><path d="M12 14v3a4 4 0 0 1-4 4H6" /></>);
export const IconLogout = base(<><path d="M9 21H6a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h3" /><path d="M16 17l5-5-5-5" /><path d="M21 12H9" /></>);
export const IconSearch = base(<><circle cx="11" cy="11" r="7" /><path d="m21 21-4.3-4.3" /></>);
export const IconPlus = base(<path d="M12 5v14M5 12h14" />);
export const IconChevronDown = base(<path d="m6 9 6 6 6-6" />);
export const IconChevronRight = base(<path d="m9 6 6 6-6 6" />);
export const IconMenu = base(<path d="M4 7h16M4 12h16M4 17h16" />);
export const IconClose = base(<path d="M6 6l12 12M18 6 6 18" />);
export const IconPaperclip = base(<path d="M21 12.5 12.5 21a5 5 0 0 1-7-7L14 5.5a3.5 3.5 0 0 1 5 5L10.5 19a2 2 0 0 1-3-3L15 8.5" />);
export const IconFileText = base(<><path d="M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8z" /><path d="M14 3v5h5" /><path d="M9 13h6M9 17h6" /></>);
export const IconImage = base(<><rect x="3" y="4" width="18" height="16" rx="2" /><circle cx="8.5" cy="9.5" r="1.5" /><path d="m21 16-5-5-11 9" /></>);
export const IconFile = base(<><path d="M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8z" /><path d="M14 3v5h5" /></>);
export const IconUpload = base(<><path d="M12 16V4M7 9l5-5 5 5" /><path d="M4 16v3a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2v-3" /></>);
export const IconDownload = base(<><path d="M12 4v12M7 11l5 5 5-5" /><path d="M4 20h16" /></>);
export const IconEye = base(<><path d="M1 12s4-7 11-7 11 7 11 7-4 7-11 7-11-7-11-7Z" /><circle cx="12" cy="12" r="3" /></>);
export const IconEyeOff = base(<><path d="M3 3l18 18" /><path d="M10.6 5.2A11 11 0 0 1 12 5c7 0 11 7 11 7a13.6 13.6 0 0 1-3.2 3.9M6.5 6.7C3.6 8.6 1 12 1 12s4 7 11 7a10.4 10.4 0 0 0 5-1.3" /><path d="M9.9 9.9a3 3 0 0 0 4.2 4.2" /></>);
export const IconUser = base(<><circle cx="12" cy="8" r="4" /><path d="M4 20c0-4 3.6-6 8-6s8 2 8 6" /></>);
export const IconBuilding = base(<><rect x="4" y="3" width="16" height="18" rx="1" /><path d="M9 8h1M14 8h1M9 12h1M14 12h1M9 16h1M14 16h1" /></>);
export const IconClock = base(<><circle cx="12" cy="12" r="9" /><path d="M12 7v5l3 2" /></>);
export const IconArrowLeft = base(<><path d="M19 12H5" /><path d="m11 18-6-6 6-6" /></>);
export const IconExternal = base(<><path d="M14 4h6v6" /><path d="M20 4 10 14" /><path d="M18 13v5a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h5" /></>);
export const IconRefresh = base(<><path d="M21 12a9 9 0 1 1-2.6-6.4" /><path d="M21 4v6h-6" /></>);
export const IconTrash = base(<><path d="M4 7h16" /><path d="M9 7V5a2 2 0 0 1 2-2h2a2 2 0 0 1 2 2v2" /><path d="M6 7l1 13a2 2 0 0 0 2 2h6a2 2 0 0 0 2-2l1-13" /></>);
export const IconCheck = base(<path d="M4 12l5 5 11-11" />);
export const IconCheckCircle = base(<><circle cx="12" cy="12" r="9" /><path d="m8 12 3 3 5-6" /></>);
export const IconXCircle = base(<><circle cx="12" cy="12" r="9" /><path d="m9.5 9.5 5 5m0-5-5 5" /></>);
export const IconAlertCircle = base(<><circle cx="12" cy="12" r="9" /><path d="M12 8v5" /><circle cx="12" cy="16" r="0.6" fill="currentColor" stroke="none" /></>);
export const IconInfo = base(<><circle cx="12" cy="12" r="9" /><path d="M12 11v5" /><circle cx="12" cy="8" r="0.6" fill="currentColor" stroke="none" /></>);
export const IconLock = base(<><rect x="4" y="10" width="16" height="10" rx="2" /><path d="M8 10V7a4 4 0 0 1 8 0v3" /></>);
export const IconMail = base(<><rect x="3" y="5" width="18" height="14" rx="2" /><path d="m4 6 8 7 8-7" /></>);
export const IconWifi = base(<><path d="M2 8.5a16 16 0 0 1 20 0" /><path d="M5.5 12.5a11 11 0 0 1 13 0" /><path d="M9 16.5a5.5 5.5 0 0 1 6 0" /><circle cx="12" cy="19.5" r="0.7" fill="currentColor" stroke="none" /></>);
export const IconStar = base(<path d="m12 3 2.6 5.6 6.2.6-4.6 4.2 1.3 6-5.5-3.1L6.5 19.4l1.3-6-4.6-4.2 6.2-.6z" />);
export const IconLayers = base(<><path d="m12 3 9 5-9 5-9-5z" /><path d="m3 13 9 5 9-5" /></>);
export const IconGrid = base(<><rect x="3" y="3" width="8" height="8" rx="1.5" /><rect x="13" y="3" width="8" height="8" rx="1.5" /><rect x="3" y="13" width="8" height="8" rx="1.5" /><rect x="13" y="13" width="8" height="8" rx="1.5" /></>);
export const IconInbox = base(<><path d="M4 12h4l2 3h4l2-3h4" /><path d="M5.5 6h13l1.5 6v6a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2v-6z" /></>);
