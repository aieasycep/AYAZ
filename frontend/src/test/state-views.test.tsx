import { describe, it, expect, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { LoadingState, ErrorState, EmptyState } from '@/components/StateViews';

// CSS modules are proxied to return empty strings — handled by vitest's
// moduleNameMapper-equivalent via the cssModulesMock setup below.

describe('LoadingState', () => {
  it('renders the spinner with default aria-label when no message given', () => {
    render(<LoadingState />);
    expect(screen.getByRole('status')).toHaveAttribute('aria-label', 'Yükleniyor');
  });

  it('renders the custom message text', () => {
    render(<LoadingState message="Veriler yükleniyor..." />);
    expect(screen.getByText('Veriler yükleniyor...')).toBeInTheDocument();
  });

  it('uses message as aria-label on the spinner when message is provided', () => {
    render(<LoadingState message="Yükleniyor, lütfen bekleyin" />);
    expect(screen.getByRole('status')).toHaveAttribute(
      'aria-label',
      'Yükleniyor, lütfen bekleyin',
    );
  });
});

describe('ErrorState', () => {
  it('renders the error message', () => {
    render(<ErrorState message="Bir hata oluştu." />);
    expect(screen.getByText('Bir hata oluştu.')).toBeInTheDocument();
  });

  it('renders an alert role container', () => {
    render(<ErrorState message="Hata!" />);
    expect(screen.getByRole('alert')).toBeInTheDocument();
  });

  it('renders the retry button when onRetry is provided', () => {
    const onRetry = vi.fn();
    render(<ErrorState message="Hata!" onRetry={onRetry} />);
    expect(screen.getByRole('button', { name: 'Tekrar dene' })).toBeInTheDocument();
  });

  it('does not render the retry button when onRetry is absent', () => {
    render(<ErrorState message="Hata!" />);
    expect(screen.queryByRole('button')).toBeNull();
  });

  it('calls onRetry when the retry button is clicked', async () => {
    const user = userEvent.setup();
    const onRetry = vi.fn();
    render(<ErrorState message="Hata!" onRetry={onRetry} />);
    await user.click(screen.getByRole('button', { name: 'Tekrar dene' }));
    expect(onRetry).toHaveBeenCalledTimes(1);
  });
});

describe('EmptyState', () => {
  it('renders the title', () => {
    render(<EmptyState title="Henüz veri yok." />);
    expect(screen.getByText('Henüz veri yok.')).toBeInTheDocument();
  });

  it('renders description when provided', () => {
    render(<EmptyState title="Boş" description="Buraya veri ekleyin." />);
    expect(screen.getByText('Buraya veri ekleyin.')).toBeInTheDocument();
  });

  it('does not render description element when absent', () => {
    render(<EmptyState title="Boş" />);
    expect(screen.queryByText(/ekleyin/)).toBeNull();
  });

  it('renders CTA content when provided', async () => {
    const user = userEvent.setup();
    const onClick = vi.fn();
    render(
      <EmptyState
        title="Boş"
        cta={<button onClick={onClick}>Bağlantı ekle</button>}
      />,
    );
    const btn = screen.getByRole('button', { name: 'Bağlantı ekle' });
    expect(btn).toBeInTheDocument();
    await user.click(btn);
    expect(onClick).toHaveBeenCalledTimes(1);
  });
});
