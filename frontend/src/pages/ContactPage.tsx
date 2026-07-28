import { useEffect } from 'react';
import { Link } from '../app/router';
import { useThemeStore } from '../store/themeStore';
import './contact.css';

const LINKEDIN_URL = 'https://www.linkedin.com/in/deepak-krishna-dev/';
const CONTACT_EMAIL = 'deepakkrishna2206@gmail.com';

export function ContactPage() {
  const isDark = useThemeStore((s) => s.dark);

  useEffect(() => {
    document.title = 'Maris AI | Contact';
  }, []);

  return (
    <div className={`contact-page ${isDark ? '' : 'contact-page--light'}`}>
      <main className="contact-card">
        <h1>Contact the developer</h1>
        <p>
          Questions, bug reports, or just want to talk about ocean data? Reach out directly, or
          use the <Link to="/feedback">feedback form</Link> for anything you'd like recorded.
        </p>

        <div className="contact-links">
          <a className="contact-link" href={LINKEDIN_URL} target="_blank" rel="noreferrer">
            <LinkedInIcon size={20} />
            <span>LinkedIn</span>
          </a>
          <a className="contact-link" href={`mailto:${CONTACT_EMAIL}`}>
            <MailIcon size={20} />
            <span>{CONTACT_EMAIL}</span>
          </a>
        </div>
      </main>
    </div>
  );
}

function LinkedInIcon({ size = 20 }: { size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="currentColor" aria-hidden="true">
      <path d="M20.45 20.45h-3.55v-5.57c0-1.33-.02-3.03-1.85-3.03-1.86 0-2.15 1.45-2.15 2.94v5.66H9.35V9h3.41v1.56h.05c.47-.9 1.63-1.85 3.36-1.85 3.6 0 4.26 2.37 4.26 5.45v6.29ZM5.34 7.43a2.06 2.06 0 1 1 0-4.12 2.06 2.06 0 0 1 0 4.12ZM7.12 20.45H3.56V9h3.56v11.45Z" />
    </svg>
  );
}

function MailIcon({ size = 20 }: { size?: number }) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.8"
      aria-hidden="true"
    >
      <rect x="3" y="5" width="18" height="14" rx="2" />
      <path d="m3 7 9 6 9-6" />
    </svg>
  );
}
