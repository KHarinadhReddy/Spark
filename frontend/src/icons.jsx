function Svg({ size = 20, filled = false, children, ...props }) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill={filled ? "currentColor" : "none"}
      stroke={filled ? "none" : "currentColor"}
      strokeWidth="1.8"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
      focusable="false"
      {...props}
    >
      {children}
    </svg>
  );
}

export function SparkIcon({ size = 24, ...props }) {
  return (
    <Svg size={size} filled {...props}>
      <path d="M12 1.8l2.3 7.4 7.5 2.3-7.5 2.3-2.3 7.4-2.3-7.4L2.2 11.5l7.5-2.3L12 1.8Z" />
      <path d="M19 16.4l.8 2.2 2.2.8-2.2.8-.8 2.2-.8-2.2-2.2-.8 2.2-.8.8-2.2Z" opacity=".8" />
    </Svg>
  );
}

export function SunIcon(props) {
  return (
    <Svg {...props}>
      <circle cx="12" cy="12" r="4" />
      <path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4" />
    </Svg>
  );
}

export function MicIcon(props) {
  return (
    <Svg {...props}>
      <path d="M12 2a3 3 0 0 0-3 3v7a3 3 0 0 0 6 0V5a3 3 0 0 0-3-3Z" />
      <path d="M19 10v2a7 7 0 0 1-14 0v-2" />
      <path d="M12 19v3M8 22h8" />
    </Svg>
  );
}

export function SendIcon(props) {
  return (
    <Svg {...props}>
      <path d="M22 2 11 13" />
      <path d="M22 2l-7 20-4-9-9-4 20-7Z" />
    </Svg>
  );
}

export function PlayIcon({ size = 20, ...props }) {
  return (
    <Svg size={size} filled {...props}>
      <path d="M7 4.5v15l13-7.5L7 4.5Z" />
    </Svg>
  );
}

export function StopIcon({ size = 20, ...props }) {
  return (
    <Svg size={size} filled {...props}>
      <rect x="6" y="6" width="12" height="12" rx="2" />
    </Svg>
  );
}

export function CalendarIcon(props) {
  return (
    <Svg {...props}>
      <rect x="3" y="4" width="18" height="17" rx="3" />
      <path d="M16 2v4M8 2v4M3 9.5h18" />
    </Svg>
  );
}

export function MailIcon(props) {
  return (
    <Svg {...props}>
      <rect x="2" y="4.5" width="20" height="15" rx="3" />
      <path d="m3 7 9 6 9-6" />
    </Svg>
  );
}

export function DriveIcon(props) {
  return (
    <Svg {...props}>
      <path d="M9.2 3 2.6 15h5.9L15 3H9.2Z" />
      <path d="m21.4 15-3.5-6.4h-5.8L15.6 15h5.8Z" />
      <path d="M2.6 15 6 21h12l3.4-6H2.6Z" />
    </Svg>
  );
}

export function ActivityIcon(props) {
  return (
    <Svg {...props}>
      <path d="M3 12h4l2.5-7 4.5 14 2.5-7H21" />
    </Svg>
  );
}

export function CheckIcon(props) {
  return (
    <Svg {...props}>
      <path d="M20 6 9 17l-5-5" />
    </Svg>
  );
}

export function XIcon(props) {
  return (
    <Svg {...props}>
      <path d="M18 6 6 18M6 6l12 12" />
    </Svg>
  );
}

export function UndoIcon(props) {
  return (
    <Svg {...props}>
      <path d="M9 14 4 9l5-5" />
      <path d="M4 9h10a6 6 0 0 1 0 12h-3" />
    </Svg>
  );
}

export function ShieldIcon(props) {
  return (
    <Svg {...props}>
      <path d="M12 22s8-4 8-10V5.5L12 2 4 5.5V12c0 6 8 10 8 10Z" />
      <path d="m9 12 2 2 4-4" />
    </Svg>
  );
}

export function VolumeIcon(props) {
  return (
    <Svg {...props}>
      <path d="M11 5 6 9H2v6h4l5 4V5Z" />
      <path d="M15.5 8.5a5 5 0 0 1 0 7M19 5a10 10 0 0 1 0 14" />
    </Svg>
  );
}

export function AlertIcon(props) {
  return (
    <Svg {...props}>
      <path d="m21.7 18-8-14a2 2 0 0 0-3.4 0l-8 14A2 2 0 0 0 4 21h16a2 2 0 0 0 1.7-3Z" />
      <path d="M12 9v4M12 17h.01" />
    </Svg>
  );
}

export function ClockIcon(props) {
  return (
    <Svg {...props}>
      <circle cx="12" cy="12" r="9" />
      <path d="M12 7v5l3 2" />
    </Svg>
  );
}

export function PlusIcon(props) {
  return (
    <Svg {...props}>
      <path d="M12 5v14M5 12h14" />
    </Svg>
  );
}

export function RefreshIcon(props) {
  return (
    <Svg {...props}>
      <path d="M21 12a9 9 0 1 1-2.6-6.4" />
      <path d="M21 3v6h-6" />
    </Svg>
  );
}

export function ArrowRightIcon(props) {
  return (
    <Svg {...props}>
      <path d="M5 12h14M13 6l6 6-6 6" />
    </Svg>
  );
}

export function SearchIcon(props) {
  return (
    <Svg {...props}>
      <circle cx="11" cy="11" r="7" />
      <path d="m20 20-3.5-3.5" />
    </Svg>
  );
}

export function FileIcon(props) {
  return (
    <Svg {...props}>
      <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8l-6-6Z" />
      <path d="M14 2v6h6" />
    </Svg>
  );
}

export function GlobeIcon(props) {
  return (
    <Svg {...props}>
      <circle cx="12" cy="12" r="9" />
      <path d="M3 12h18M12 3a15 15 0 0 1 0 18a15 15 0 0 1 0-18Z" />
    </Svg>
  );
}

export function ExternalIcon(props) {
  return (
    <Svg {...props}>
      <path d="M14 3h7v7M21 3l-9 9" />
      <path d="M21 14v5a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5" />
    </Svg>
  );
}
