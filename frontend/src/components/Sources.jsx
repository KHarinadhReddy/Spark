import { COPY } from "../i18n";
import { AlertIcon, CalendarIcon, FileIcon, MailIcon } from "../icons";

const ICONS = {
  email: MailIcon,
  event: CalendarIcon,
  file: FileIcon,
};

export function Sources({ sources, language }) {
  if (!sources?.length) return null;
  const t = COPY[language];
  const seen = new Set();
  const unique = sources.filter((source) => {
    const key = `${source.kind}:${source.id}`;
    if (seen.has(key)) return false;
    seen.add(key);
    return true;
  });

  return (
    <div className="sources" aria-label={t.sources}>
      <span className="sources-label">{t.sources}</span>
      <div className="source-chips">
        {unique.slice(0, 6).map((source) => {
          const Icon = ICONS[source.kind] || FileIcon;
          return (
            <span
              key={`${source.kind}:${source.id}`}
              className={`source-chip ${source.flagged ? "flagged" : ""}`}
              title={source.snippet || source.subtitle || source.title}
            >
              <Icon size={13} />
              <span>{source.title}</span>
            </span>
          );
        })}
      </div>
    </div>
  );
}

export function FlagBanner({ flags, language }) {
  if (!flags?.length) return null;
  const t = COPY[language];
  const first = flags[0];
  return (
    <div className="flag-banner" role="note">
      <span className="flag-icon">
        <AlertIcon size={18} />
      </span>
      <div>
        <strong>{t.flagTitle}</strong>
        <p>{first.source ? `“${first.source}” — ` : ""}{t.flagBody}</p>
      </div>
    </div>
  );
}
