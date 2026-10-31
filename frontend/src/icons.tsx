/** 线性 SVG 图标（stroke 2），与原型一致；禁用 emoji 充当图标 */
const S = {
  width: 16,
  height: 16,
  viewBox: "0 0 24 24",
  fill: "none",
  stroke: "currentColor",
  strokeWidth: 2,
  strokeLinecap: "round" as const,
};

export const IconPlayNav = () => (
  <svg {...S}><polygon points="6 4 20 12 6 20" strokeLinejoin="round" /></svg>
);
export const IconBook = () => (
  <svg {...S}><path d="M4 19V5a2 2 0 0 1 2-2h13v16H6a2 2 0 0 0 0 4h13" /></svg>
);
export const IconExplore = () => (
  <svg {...S}><circle cx="12" cy="12" r="9" /><path d="M8 12h8M12 8v8" /></svg>
);
export const IconLibrary = () => (
  <svg {...S}><rect x="4" y="4" width="16" height="16" rx="2" /><path d="M4 9h16M9 4v16" /></svg>
);
export const IconHeart = () => (
  <svg {...S}><path d="M12 21s-7.5-4.6-10-9.2C.6 7.6 3 4 6.5 4c2 0 3.6 1.1 5.5 3 1.9-1.9 3.5-3 5.5-3C21 4 23.4 7.6 22 11.8 19.5 16.4 12 21 12 21z" /></svg>
);
export const IconPrev = () => (
  <svg width="16" height="16" viewBox="0 0 24 24" fill="currentColor">
    <polygon points="19 20 9 12 19 4" /><rect x="5" y="4" width="2" height="16" />
  </svg>
);
export const IconNext = () => (
  <svg width="16" height="16" viewBox="0 0 24 24" fill="currentColor">
    <polygon points="5 4 15 12 5 20" /><rect x="17" y="4" width="2" height="16" />
  </svg>
);
export const IconPlay = ({ size = 14 }: { size?: number }) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill="currentColor">
    <polygon points="7 4 21 12 7 20" />
  </svg>
);
export const IconPause = ({ size = 14 }: { size?: number }) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill="currentColor">
    <rect x="5" y="4" width="5" height="16" rx="1" />
    <rect x="14" y="4" width="5" height="16" rx="1" />
  </svg>
);
export const IconSkipChorus = () => (
  <svg width="16" height="16" viewBox="0 0 24 24" fill="currentColor">
    <polygon points="4 4 12 12 4 20" /><polygon points="12 4 20 12 12 20" />
  </svg>
);
export const IconRhyme = () => (
  <svg {...S}><circle cx="12" cy="12" r="9" /><circle cx="12" cy="12" r="5" />
    <circle cx="12" cy="12" r="1.2" fill="currentColor" /></svg>
);
export const IconVolume = () => (
  <svg width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2} strokeLinecap="round">
    <path d="M11 5 6 9H3v6h3l5 4V5z" strokeLinejoin="round" />
    <path d="M15.5 8.5a5 5 0 0 1 0 7M18.5 5.5a9 9 0 0 1 0 13" />
  </svg>
);
export const IconGear = () => (
  <svg {...S}><circle cx="12" cy="12" r="3" />
    <path d="M19.4 15a1.7 1.7 0 0 0 .34 1.87l.06.06a2 2 0 1 1-2.83 2.83l-.06-.06a1.7 1.7 0 0 0-1.87-.34 1.7 1.7 0 0 0-1 1.55V21a2 2 0 1 1-4 0v-.09a1.7 1.7 0 0 0-1-1.55 1.7 1.7 0 0 0-1.87.34l-.06.06a2 2 0 1 1-2.83-2.83l.06-.06a1.7 1.7 0 0 0 .34-1.87 1.7 1.7 0 0 0-1.55-1H3a2 2 0 1 1 0-4h.09a1.7 1.7 0 0 0 1.55-1 1.7 1.7 0 0 0-.34-1.87l-.06-.06a2 2 0 1 1 2.83-2.83l.06.06a1.7 1.7 0 0 0 1.87.34h.01a1.7 1.7 0 0 0 1-1.55V3a2 2 0 1 1 4 0v.09a1.7 1.7 0 0 0 1 1.55 1.7 1.7 0 0 0 1.87-.34l.06-.06a2 2 0 1 1 2.83 2.83l-.06.06a1.7 1.7 0 0 0-.34 1.87v.01a1.7 1.7 0 0 0 1.55 1H21a2 2 0 1 1 0 4h-.09a1.7 1.7 0 0 0-1.55 1z" strokeLinejoin="round" /></svg>
);
export const IconNote = () => (
  <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="#0e1016" strokeWidth={2.4} strokeLinecap="round">
    <path d="M9 18V6l10-2v12" /><circle cx="6.5" cy="18" r="2.5" /><circle cx="16.5" cy="16" r="2.5" />
  </svg>
);
