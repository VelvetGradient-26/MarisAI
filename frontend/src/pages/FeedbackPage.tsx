import { useEffect, useState } from 'react';
import type { SubmitEvent } from 'react';
import { sendFeedback } from '../features/map/api/feedback';
import { useThemeStore } from '../store/themeStore';
import './feedback.css';

type Status = 'idle' | 'loading' | 'success' | 'error';

export function FeedbackPage() {
  const isDark = useThemeStore((s) => s.dark);
  const [name, setName] = useState('');
  const [email, setEmail] = useState('');
  const [message, setMessage] = useState('');
  const [status, setStatus] = useState<Status>('idle');
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    document.title = 'Maris AI | Feedback';
  }, []);

  async function handleSubmit(e: SubmitEvent<HTMLFormElement>) {
    e.preventDefault();
    setError(null);
    setStatus('loading');
    try {
      await sendFeedback({ name, email, message });
      setStatus('success');
      setName('');
      setEmail('');
      setMessage('');
    } catch (err) {
      setStatus('error');
      setError(err instanceof Error ? err.message : 'Failed to send feedback.');
    }
  }

  return (
    <div className={`feedback-page ${isDark ? '' : 'feedback-page--light'}`}>
      <form className="feedback-card" onSubmit={handleSubmit}>
        <h1>Send feedback</h1>
        <p>Found a bug, have an idea, or just want to say hi? This goes straight to the team.</p>

        <label>
          Name
          <input
            type="text"
            required
            value={name}
            onChange={(e) => setName(e.target.value)}
            disabled={status === 'loading'}
          />
        </label>

        <label>
          Email
          <input
            type="email"
            required
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            disabled={status === 'loading'}
          />
        </label>

        <label>
          Message
          <textarea
            required
            rows={6}
            value={message}
            onChange={(e) => setMessage(e.target.value)}
            disabled={status === 'loading'}
          />
        </label>

        {status === 'error' && error && <p className="feedback-error">{error}</p>}
        {status === 'success' && (
          <p className="feedback-success">Thanks — your feedback has been sent.</p>
        )}

        <button type="submit" className="feedback-submit" disabled={status === 'loading'}>
          {status === 'loading' ? 'Sending…' : 'Send feedback'}
        </button>
      </form>
    </div>
  );
}
